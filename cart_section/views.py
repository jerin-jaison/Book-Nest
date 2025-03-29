from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_http_methods
from .models import Cart, Address, Order, OrderItem
from admin_side.models import Product, Coupon, CouponUsage, ReferralHistory, ProductOffer, CategoryOffer
from user_profile.models import Wishlist as ProfileWishlist, WishlistItem, AccountDetails
from user_authentication.models import Wishlist as AuthWishlist
from user_wallet.models import Wallet, WalletTransaction
from django.urls import reverse
from django.db.models import ProtectedError
from django.db.models import Count
from django.utils import timezone
from user_wallet.views import add_referral_reward
from decimal import Decimal
import uuid
import json
import random
import string
from datetime import datetime, timedelta
from django.db.models import Q
import logging

MAX_QUANTITY_PER_ITEM = 5  
DELIVERY_CHARGE = 40  # Fixed delivery charge
DISCOUNT_PERCENTAGE = 0  # No default discount
REFERRAL_REWARD_AMOUNT = Decimal('100.00')  # Fixed reward amount of 100 rupees

# Constants
TAX_RATE = Decimal('0.05')  # 5% tax rate

logger = logging.getLogger(__name__)

# Helper function to generate a unique coupon code
def generate_unique_coupon_code(length=8):
    """Generate a unique coupon code"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if not Coupon.objects.filter(code=code).exists():
            return code

# Helper function to create a referral reward coupon
def create_referral_reward_coupon(user, order_id):
    """
    Create a coupon as a referral reward
    
    Args:
        user: The user who referred the customer
        order_id: The order ID for reference
    
    Returns:
        Coupon: The created coupon object or None if failed
    """
    try:
        # Generate a unique coupon code
        code = generate_unique_coupon_code()
        
        # Set expiry date to 30 days from now
        expiry_date = timezone.now() + timedelta(days=30)
        
        # Create the coupon
        coupon = Coupon.objects.create(
            user=user,
            code=code,
            discount_amount=REFERRAL_REWARD_AMOUNT,
            discount_percentage=None,
            min_purchase_amount=Decimal('0.00'),
            is_active=True,
            expiry_date=expiry_date,
            is_admin_generated=False  # This is a referral coupon, not admin generated
        )
        
        # Send notification to user (could be implemented later)
        
        return coupon
    except Exception as e:
        print(f"Error creating referral reward coupon: {str(e)}")
        return None

@login_required(login_url='login_page')
def view_cart(request):
    cart_items = Cart.objects.filter(user=request.user).select_related('product')
    subtotal = sum(item.total_price for item in cart_items)
    discount = round((subtotal * DISCOUNT_PERCENTAGE) / 100)
    delivery_charge = DELIVERY_CHARGE if cart_items else 0
    total_amount = subtotal - discount + delivery_charge
    all_items_valid = all(item.is_valid_for_checkout for item in cart_items)
    
    # Get current time for offer validation
    now = timezone.now()
    
    context = {
        'cart_items': cart_items,
        'subtotal': subtotal,
        'discount': discount,
        'discount_percentage': DISCOUNT_PERCENTAGE,
        'delivery_charge': delivery_charge,
        'total_amount': total_amount,
        'max_quantity': MAX_QUANTITY_PER_ITEM,
        'all_items_valid': all_items_valid,
        'now': now,  # Pass current time for offer validation
    }
    return render(request, 'cart.html', context)

@login_required(login_url='login_page')
def checkout(request):
    # Check if this is a payment retry
    is_retry = request.GET.get('retry_payment') == 'true'
    retry_order_id = request.session.get('retry_order_id')
    
    if is_retry and retry_order_id:
        # Get the order being retried
        try:
            # Only check order ID and user, don't filter by status initially
            retry_order = Order.objects.get(order_id=retry_order_id, user=request.user)
            
            # Print debug info
            print(f"Found order for retry: {retry_order_id}, status: {retry_order.status}, payment_status: {retry_order.payment_status}")
            
            # Check if order status is valid for retry (be more permissive)
            if retry_order.status not in ['PENDING', 'CONFIRMED'] and retry_order.payment_status != 'PAID':
                messages.warning(request, f"This order (status: {retry_order.status}) cannot be retried. Only pending or confirmed orders with unpaid status can be retried.")
                if 'retry_order_id' in request.session:
                    del request.session['retry_order_id']
                if 'retry_order_total' in request.session:
                    del request.session['retry_order_total']
                return redirect('cart_section:view_cart')
            
            # Get the order items
            order_items = retry_order.items.all().select_related('product')
            
            # Get user's addresses
            addresses = Address.objects.filter(user=request.user).order_by('-is_default', '-created_at')
            
            # Mark addresses that are used in orders
            addresses_with_orders = list(Order.objects.filter(address__in=addresses).values('address').annotate(count=Count('id')))
            addresses_in_use = {item['address']: item['count'] for item in addresses_with_orders}
            
            # Get the coupon discount from the session
            coupon_discount = Decimal(request.session.get('coupon_discount', '0.0'))
            
            # Get user's wallet balance
            try:
                wallet = Wallet.objects.get(user=request.user)
                wallet_balance = wallet.balance
            except Wallet.DoesNotExist:
                wallet = None
                wallet_balance = Decimal('0.00')
            
            # Indicate this is a retry payment - only allow RAZORPAY payment
            payment_methods = [
                {'id': 'RAZORPAY', 'name': 'Online Payment (Credit/Debit Card, UPI, etc.)'}
            ]
            
            context = {
                'order': retry_order,
                'order_items': order_items,
                'addresses': addresses,
                'addresses_in_use': addresses_in_use,
                'is_retry': True,
                'total': retry_order.total,
                'payment_methods': payment_methods,  # Only RAZORPAY for retry
                'wallet': wallet,  # Add wallet object to context
                'wallet_balance': wallet_balance,
                'coupon_discount': coupon_discount,
            }
            
            return render(request, 'checkout.html', context)
            
        except Order.DoesNotExist:
            messages.error(request, "Order not found.")
            return redirect('cart_section:view_cart')
    
    # Regular checkout flow for new orders
    cart_items = Cart.objects.filter(user=request.user).select_related('product')
    
    if not cart_items:
        messages.warning(request, "Your cart is empty. Add items before checkout.")
        return redirect('cart_section:view_cart')
    
    # Get user's addresses
    addresses = Address.objects.filter(user=request.user).order_by('-is_default', '-created_at')
    
    # Calculate totals
    subtotal = sum(item.product.final_price * item.quantity for item in cart_items)
    
    # Apply coupon discount if any
    coupon_discount = Decimal('0.00')
    coupon_code = request.session.get('coupon_code')
    applied_coupon = None
    
    if coupon_code:
        try:
            # Check for user-specific or global coupon
            coupon = Coupon.objects.filter(
                code=coupon_code, 
                is_active=True,
                expiry_date__gt=timezone.now()
            ).filter(
                Q(user=request.user) | Q(user__isnull=True)
            ).first()
            
            if coupon:
                # Add coupon validation logic here
                if coupon.discount_percentage:
                    coupon_discount = round((subtotal * coupon.discount_percentage) / 100, 2)
                else:
                    coupon_discount = coupon.discount_amount
                    
                request.session['coupon_discount'] = str(coupon_discount)
                applied_coupon = coupon_code
            else:
                if 'coupon_code' in request.session:
                    del request.session['coupon_code']
                if 'coupon_discount' in request.session:
                    del request.session['coupon_discount']
        except Exception as e:
            print(f"Error applying coupon: {str(e)}")
            if 'coupon_code' in request.session:
                del request.session['coupon_code']
            if 'coupon_discount' in request.session:
                del request.session['coupon_discount']
    
    # Fixed delivery charge
    delivery_charge = DELIVERY_CHARGE
    
    # Calculate total
    total = subtotal - coupon_discount + delivery_charge
    
    # Get user's wallet balance
    try:
        wallet = Wallet.objects.get(user=request.user)
        wallet_balance = wallet.balance
    except Wallet.DoesNotExist:
        wallet = None
        wallet_balance = Decimal('0.00')
    
    # Setup payment methods
    payment_methods = [
        {'id': 'RAZORPAY', 'name': 'Online Payment (Credit/Debit Card, UPI, etc.)'},
        {'id': 'COD', 'name': 'Cash on Delivery'},
    ]
    
    # Check if wallet payment is available
    if wallet and wallet_balance > 0:
        payment_methods.append({'id': 'WALLET', 'name': f'Wallet (₹{wallet_balance})'})
    
    # Determine default payment method based on order total
    default_payment_method = 'RAZORPAY' if total > 5000 else 'COD'
    
    # If wallet balance is sufficient, prefer wallet
    if wallet and wallet_balance >= total:
        default_payment_method = 'WALLET'
    
    # Get eligible coupons for this order
    from admin_side.models import Coupon, CouponUsage
    from django.db.models import Q
    
    # Get user-specific coupons
    user_coupons = Coupon.objects.filter(
        user=request.user,
        is_active=True,
        expiry_date__gt=timezone.now(),
        min_purchase_amount__lte=subtotal
    )
    
    # Get global coupons
    global_coupons = Coupon.objects.filter(
        user__isnull=True,
        is_active=True,
        expiry_date__gt=timezone.now(),
        min_purchase_amount__lte=subtotal
    )
    
    # Combine coupons
    all_eligible_coupons = list(user_coupons) + list(global_coupons)
    
    # Exclude coupons that have already been used by this user
    used_coupon_codes = set(CouponUsage.objects.filter(user=request.user).values_list('coupon__code', flat=True))
    eligible_coupons = [coupon for coupon in all_eligible_coupons if coupon.code not in used_coupon_codes]
    
    # Add discount display to coupons
    for coupon in eligible_coupons:
        if coupon.discount_percentage:
            coupon.discount_display = f"{coupon.discount_percentage}% OFF"
            coupon.discount_value = round((subtotal * coupon.discount_percentage) / 100, 2)
        else:
            coupon.discount_display = f"₹{coupon.discount_amount} OFF"
            coupon.discount_value = coupon.discount_amount
    
    # Sort coupons by discount value (highest first)
    eligible_coupons.sort(key=lambda x: x.discount_value, reverse=True)
    
    # Mark the best value coupon
    if eligible_coupons:
        eligible_coupons[0].is_best_value = True
    
    context = {
        'cart_items': cart_items,
        'addresses': addresses,
        'subtotal': subtotal,
        'coupon_discount': coupon_discount,
        'delivery_charge': delivery_charge,
        'total': total,
        'total_amount': total,  # For consistency with template
        'payment_methods': payment_methods,
        'wallet': wallet,
        'wallet_balance': wallet_balance,
        'coupon_code': coupon_code,
        'applied_coupon': applied_coupon,
        'default_payment_method': default_payment_method,
        'eligible_coupons': eligible_coupons,
    }
    
    return render(request, 'checkout.html', context)

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def add_address(request):
    try:
        # Form validation
        required_fields = ['full_name', 'phone_number', 'pincode', 'house_no', 'area', 'city', 'state']
        for field in required_fields:
            if not request.POST.get(field):
                return JsonResponse({
                    'status': 'error',
                    'message': f'{field.replace("_", " ").title()} is required'
                })
        
        # Validate phone number (10 digits)
        phone_number = request.POST['phone_number']
        if not phone_number.isdigit() or len(phone_number) != 10:
            return JsonResponse({
                'status': 'error',
                'message': 'Please enter a valid 10-digit phone number'
            })
        
        # Validate pincode (6 digits)
        pincode = request.POST['pincode']
        if not pincode.isdigit() or len(pincode) != 6:
            return JsonResponse({
                'status': 'error',
                'message': 'Please enter a valid 6-digit pincode'
            })

        # If this is the first address, make it default
        is_default = request.POST.get('is_default') == 'on'
        if not Address.objects.filter(user=request.user).exists():
            is_default = True
        elif is_default:
            # If this address is being set as default, remove default from other addresses
            Address.objects.filter(user=request.user, is_default=True).update(is_default=False)

        # Create new address
        address = Address(
            user=request.user,
            full_name=request.POST['full_name'],
            phone_number=phone_number,
            pincode=pincode,
            house_no=request.POST['house_no'],
            area=request.POST['area'],
            landmark=request.POST.get('landmark', ''),
            city=request.POST['city'],
            state=request.POST['state'],
            is_default=is_default
        )
        address.save()

        # Return the new address details along with success message
        return JsonResponse({
            'status': 'success',
            'message': 'Address added successfully',
            'address': {
                'id': address.id,
                'full_name': address.full_name,
                'phone_number': address.phone_number,
                'pincode': address.pincode,
                'house_no': address.house_no,
                'area': address.area,
                'landmark': address.landmark,
                'city': address.city,
                'state': address.state,
                'is_default': address.is_default
            }
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error adding address: {str(e)}'
        })

@login_required(login_url='login_page')
def get_address(request, address_id):
    try:
        address = get_object_or_404(Address, id=address_id, user=request.user)
        return JsonResponse({
            'status': 'success',
            'address': {
                'id': address.id,
                'full_name': address.full_name,
                'phone_number': address.phone_number,
                'pincode': address.pincode,
                'house_no': address.house_no,
                'area': address.area,
                'landmark': address.landmark,
                'city': address.city,
                'state': address.state,
                'is_default': address.is_default
            }
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def update_address(request, address_id):
    try:
        address = get_object_or_404(Address, id=address_id, user=request.user)
        address.full_name = request.POST['full_name']
        address.phone_number = request.POST['phone_number']
        address.pincode = request.POST['pincode']
        address.house_no = request.POST['house_no']
        address.area = request.POST['area']
        address.landmark = request.POST.get('landmark', '')
        address.city = request.POST['city']
        address.state = request.POST['state']
        address.is_default = request.POST.get('is_default') == 'on'
        address.save()
        return JsonResponse({'status': 'success', 'message': 'Address updated successfully'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def make_default_address(request, address_id):
    try:
        address = get_object_or_404(Address, id=address_id, user=request.user)
        address.is_default = True
        address.save()
        return JsonResponse({'status': 'success', 'message': 'Default address updated'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def delete_address(request, address_id):
    try:
        address = get_object_or_404(Address, id=address_id, user=request.user)
        
        # Check if this is the only address
        if Address.objects.filter(user=request.user).count() == 1:
            return JsonResponse({
                'status': 'error',
                'message': 'Cannot delete the only address. Please add another address first.'
            })
        
        # Check if this address is used in any orders
        try:
            # If this is the default address, make another address default
            if address.is_default:
                other_address = Address.objects.filter(user=request.user).exclude(id=address_id).first()
                if other_address:
                    other_address.is_default = True
                    other_address.save()
            
            # Try to delete the address
            address.delete()
            
            return JsonResponse({
                'status': 'success',
                'message': 'Address deleted successfully'
            })
        except ProtectedError as e:
            # Address is referenced by orders
            return JsonResponse({
                'status': 'error',
                'message': 'This address cannot be deleted because it is used in existing orders. You can add a new address instead.'
            })
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        })

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def place_order(request):
    try:
        # First, check if the data was sent as JSON or as form data
        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body)
                payment_method = data.get('payment_method')
                address_id = data.get('address_id')
                use_wallet = data.get('use_wallet', False)
            else:
                payment_method = request.POST.get('payment_method')
                address_id = request.POST.get('selected_address_id')
                use_wallet = request.POST.get('use_wallet', False) == 'true'
        except json.JSONDecodeError:
            # If JSON parsing fails, fall back to form data
            payment_method = request.POST.get('payment_method')
            address_id = request.POST.get('selected_address_id')
            use_wallet = request.POST.get('use_wallet', False) == 'true'
        
        # Check if this is a payment retry
        retry_order_id = request.session.get('retry_order_id')
        is_retry = retry_order_id is not None
        
        if is_retry:
            try:
                # Get the order being retried
                order = Order.objects.get(order_id=retry_order_id, user=request.user)
                
                # Verify the order is eligible for retry
                if order.status not in ['PENDING', 'CONFIRMED'] or order.payment_status == 'PAID':
                    return JsonResponse({
                        'status': 'error', 
                        'message': f'This order (status: {order.status}, payment: {order.payment_status}) is not eligible for payment retry.'
                    })
                
                # Update payment method
                order.payment_method = payment_method
                
                # Update address if different
                if address_id:
                    try:
                        new_address = Address.objects.get(id=address_id, user=request.user)
                        order.address = new_address
                    except Address.DoesNotExist:
                        return JsonResponse({'status': 'error', 'message': 'Invalid address'})
                
                # Update wallet usage if changed
                order.used_wallet = use_wallet
                order.save()
                
                # Clear retry session data
                if 'retry_order_id' in request.session:
                    del request.session['retry_order_id']
                if 'retry_order_total' in request.session:
                    del request.session['retry_order_total']
                
                # For COD, redirect to order_placed directly
                if payment_method == 'COD':
                    # Check if order amount exceeds COD limit
                    if order.total > 5000:
                        return JsonResponse({
                            'status': 'error',
                            'message': 'Cash on Delivery is not available for orders above ₹5,000. Please choose online payment.'
                        })
                    
                    return JsonResponse({
                        'status': 'success',
                        'order_id': order.order_id,
                        'redirect_url': reverse('cart_section:order_placed')
                    })
                # For RAZORPAY, redirect to payment page
                elif payment_method == 'RAZORPAY':
                    return JsonResponse({
                        'status': 'success',
                        'order_id': order.order_id,
                        'redirect_url': reverse('online_payment:initiate_payment', args=[order.order_id])
                    })
                # For other payment methods
                else:
                    return JsonResponse({
                        'status': 'success',
                        'order_id': order.order_id,
                        'redirect_url': reverse('cart_section:order_placed')
                    })
            except Order.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Invalid order for retry'})
        
        # For regular new orders, continue with the existing code
        with transaction.atomic():
            payment_method = request.POST.get('payment_method', 'COD')
            
            # Get address
            try:
                address = Address.objects.get(id=address_id, user=request.user)
            except Address.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Please select a valid shipping address'})
            
            # Get cart items
            cart_items = Cart.objects.filter(user=request.user)
            if not cart_items.exists():
                return JsonResponse({'status': 'error', 'message': 'Your cart is empty'})
            
            # Calculate totals
            subtotal = sum(item.total_price for item in cart_items)
            discount = round((subtotal * DISCOUNT_PERCENTAGE) / 100)
            total = subtotal - discount + DELIVERY_CHARGE
            
            # Apply coupon if it exists in the session (NOT from the current request)
            coupon_discount = 0
            coupon = None
            coupon_code = request.session.get('coupon_code')
            
            if coupon_code:
                try:
                    # Try to find a valid coupon (user-specific or global)
                    coupon = Coupon.objects.filter(
                        code__iexact=coupon_code,  # Case-insensitive matching
                        is_active=True,
                        expiry_date__gt=timezone.now()
                    ).filter(
                        Q(user=request.user) | Q(user__isnull=True)
                    ).first()
                    
                    if coupon:
                        # Check if the user has already used this coupon
                        if not CouponUsage.objects.filter(coupon=coupon, user=request.user).exists():
                            # Check minimum purchase amount
                            if subtotal >= coupon.min_purchase_amount:
                                # Calculate discount
                                if coupon.discount_percentage:
                                    coupon_discount = round((subtotal * coupon.discount_percentage) / 100)
                                else:
                                    coupon_discount = coupon.discount_amount
                                
                                # Update total
                                total = total - coupon_discount
                                
                                # Ensure total is not negative
                                if total < 0:
                                    total = 0
                except Exception as e:
                    print(f"Error applying coupon from session: {str(e)}")
                    traceback.print_exc()
                    # Continue without coupon if there's an error
                    coupon = None
            
            # For COD orders, handle separately with guaranteed success
            if payment_method == 'COD':
                # Check if order amount exceeds COD limit
                if total > 5000:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Cash on Delivery is not available for orders above ₹5,000. Please choose online payment.'
                    })
                
                # Create order
                order = Order.objects.create(
                    user=request.user,
                    address=address,
                    subtotal=subtotal,
                    discount=discount + coupon_discount,
                    delivery_charge=DELIVERY_CHARGE,
                    total=total,
                    payment_method='COD',
                    payment_status='PENDING',
                    status='CONFIRMED'
                )
                
                # Create order items and update stock
                for cart_item in cart_items:
                    product = cart_item.product
                    
                    # Create order item
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=cart_item.quantity,
                        price=product.final_price,
                        total=cart_item.total_price
                    )
                    
                    # Update stock
                    product.stock -= cart_item.quantity
                    product.save()
                
                # Mark coupon as used if applied
                if coupon:
                    CouponUsage.objects.create(
                        coupon=coupon,
                        user=request.user,
                        order=order
                    )
                
                # Process referral reward
                try:
                    referral_history = ReferralHistory.objects.filter(referred_user=request.user).first()
                    if referral_history and not referral_history.reward_given:
                        coupon = create_referral_reward_coupon(
                            user=referral_history.referrer,
                            order_id=order.order_id
                        )
                        if coupon:
                            referral_history.reward_given = True
                            referral_history.save()
                            order.notes = f"Referral reward coupon created: {coupon.code}"
                            order.save()
                except Exception as e:
                    print(f"Error processing referral reward: {str(e)}")
                
                # Clear cart and session
                cart_items.delete()
                if 'coupon_code' in request.session:
                    del request.session['coupon_code']
                if 'coupon_discount' in request.session:
                    del request.session['coupon_discount']
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Order placed successfully',
                    'order_id': order.order_id,
                    'redirect_url': reverse('cart_section:order_placed')
                })
            
            # For the WALLET payment method, process payment immediately
            elif payment_method == 'WALLET':
                # Get user's wallet
                try:
                    wallet = Wallet.objects.get(user=request.user)
                except Wallet.DoesNotExist:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Wallet not found. Please try another payment method.'
                    })
                
                # Check if user has enough balance
                if wallet.balance < total:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Insufficient wallet balance. Your balance is ₹{wallet.balance} but order total is ₹{total}'
                    })
                
                # Create order first
                order = Order.objects.create(
                    user=request.user,
                    address=address,
                    subtotal=subtotal,
                    discount=discount + coupon_discount,
                    delivery_charge=DELIVERY_CHARGE,
                    total=total,
                    payment_method='WALLET',
                    payment_status='PAID',
                    status='CONFIRMED'
                )
                
                # Create order items and update stock
                for cart_item in cart_items:
                    product = cart_item.product
                    
                    # Create order item with individual status
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=cart_item.quantity,
                        price=product.final_price,
                        total=cart_item.total_price,
                        status='CONFIRMED'  # Set initial status for each item
                    )
                    
                    # Update stock
                    product.stock -= cart_item.quantity
                    product.save()
                
                # Mark coupon as used if applied
                if coupon:
                    CouponUsage.objects.create(
                        coupon=coupon,
                        user=request.user,
                        order=order
                    )
                
                # Deduct amount from wallet and create transaction record
                with transaction.atomic():
                    # Deduct amount from wallet
                    wallet.balance -= total
                    wallet.save()
                    
                    # Create wallet transaction record
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        amount=total,
                        transaction_type='DEBIT',
                        status='COMPLETED',
                        description=f"Payment for order #{order.order_id}",
                        reference_id=order.order_id
                    )
                
                # Clear cart and session
                cart_items.delete()
                if 'coupon_code' in request.session:
                    del request.session['coupon_code']
                if 'coupon_discount' in request.session:
                    del request.session['coupon_discount']
                
                return JsonResponse({
                    'status': 'success',
                    'message': f'Order placed successfully! ₹{total} deducted from your wallet. New balance: ₹{wallet.balance}',
                    'order_id': order.order_id,
                    'redirect_url': reverse('cart_section:order_placed')
                })
            
            # For RAZORPAY, create order and redirect to payment initiation page
            elif payment_method == 'RAZORPAY':
                # Create order
                order = Order.objects.create(
                    user=request.user,
                    address=address,
                    subtotal=subtotal,
                    discount=discount + coupon_discount,
                    delivery_charge=DELIVERY_CHARGE,
                    total=total,
                    payment_method='RAZORPAY',
                    payment_status='PENDING',
                    status='PENDING'
                )
                
                # Create order items and update stock
                for cart_item in cart_items:
                    product = cart_item.product
                    
                    # Create order item
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=cart_item.quantity,
                        price=product.final_price,
                        total=cart_item.total_price
                    )
                    
                    # Update stock
                    product.stock -= cart_item.quantity
                    product.save()
                
                # Mark coupon as used if applied
                if coupon:
                    CouponUsage.objects.create(
                        coupon=coupon,
                        user=request.user,
                        order=order
                    )
                
                # Clear cart and session
                cart_items.delete()
                if 'coupon_code' in request.session:
                    del request.session['coupon_code']
                if 'coupon_discount' in request.session:
                    del request.session['coupon_discount']
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Order created, redirecting to payment gateway',
                    'order_id': order.order_id,
                    'redirect_url': reverse('online_payment:initiate_payment', args=[order.order_id])
                })
            
            # For other online payment methods, create order and redirect
            else:
                # Create order
                order = Order.objects.create(
                    user=request.user,
                    address=address,
                    subtotal=subtotal,
                    discount=discount + coupon_discount,
                    delivery_charge=DELIVERY_CHARGE,
                    total=total,
                    payment_method=payment_method,
                    payment_status='PENDING',
                    status='PENDING'
                )
                
                # Create order items and update stock
                for cart_item in cart_items:
                    product = cart_item.product
                    
                    # Create order item
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=cart_item.quantity,
                        price=product.final_price,
                        total=cart_item.total_price
                    )
                    
                    # Update stock
                    product.stock -= cart_item.quantity
                    product.save()
                
                # Mark coupon as used if applied
                if coupon:
                    CouponUsage.objects.create(
                        coupon=coupon,
                        user=request.user,
                        order=order
                    )
                
                # Clear cart and session
                cart_items.delete()
                if 'coupon_code' in request.session:
                    del request.session['coupon_code']
                if 'coupon_discount' in request.session:
                    del request.session['coupon_discount']
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Order placed successfully',
                    'order_id': order.order_id,
                    'redirect_url': reverse('cart_section:order_placed')
                })
                
    except Exception as e:
        print(f"Error placing order: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'status': 'error', 'message': f'An error occurred: {str(e)}'})

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def add_to_cart(request, product_id):
    try:
        product = get_object_or_404(Product, id=product_id)
        quantity = int(request.POST.get('quantity', 1))
        
        # Check if the request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Check if product is available
        if product.status != 'active':
            message = f'Sorry, {product.title} is currently not available for purchase.'
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
            return redirect('product_page')
        
        if not product.category.is_active:
            message = f'Sorry, {product.title} is currently not available in this category.'
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
            return redirect('product_page')
        
        if product.stock <= 0:
            message = f'Sorry, {product.title} is currently out of stock.'
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
            return redirect('product_page')

        if quantity > MAX_QUANTITY_PER_ITEM:
            message = f'You can only add up to {MAX_QUANTITY_PER_ITEM} copies of {product.title} to your cart.'
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
            return redirect('product_page')

        if quantity > product.stock:
            message = f'Only {product.stock} copies of {product.title} are available in stock.'
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': message})
            messages.error(request, message)
            return redirect('product_page')

        with transaction.atomic():
            cart_item, created = Cart.objects.get_or_create(
                user=request.user,
                product=product,
                defaults={'quantity': quantity}
            )
            
            if not created:
                new_quantity = cart_item.quantity + quantity
                if new_quantity > MAX_QUANTITY_PER_ITEM:
                    message = f'You already have {cart_item.quantity} copies of {product.title} in your cart. Maximum allowed is {MAX_QUANTITY_PER_ITEM}.'
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'message': message})
                    messages.error(request, message)
                    return redirect('product_page')
                
                if new_quantity > product.stock:
                    message = f'Cannot add more copies of {product.title}. Only {product.stock} available in stock.'
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'message': message})
                    messages.error(request, message)
                    return redirect('product_page')
                
                cart_item.quantity = new_quantity
                cart_item.save()
            
            # Remove from wishlist if exists (both models)
            try:
                # Remove from user_profile wishlist
                ProfileWishlist.objects.filter(user=request.user, product=product).delete()
                WishlistItem.objects.filter(user=request.user, product=product).delete()
                
                # Remove from user_authentication wishlist
                AuthWishlist.objects.filter(user=request.user, product=product).delete()
            except Exception as e:
                print(f"Error removing from wishlist: {str(e)}")
                pass  # Ignore if Wishlist model doesn't exist or any other error
        
        cart_count = Cart.objects.filter(user=request.user).count()
        
        if created:
            success_message = f'{product.title} has been added to your cart.'
        else:
            success_message = f'Updated quantity of {product.title} in your cart to {new_quantity}.'
            
        # Handle AJAX response
        if is_ajax:
            return JsonResponse({
                'status': 'success',
                'cart_count': cart_count,
                'message': success_message
            })
        
        # Handle non-AJAX response
        messages.success(request, success_message)
        
        # Determine the redirect URL based on referer if available
        referer = request.META.get('HTTP_REFERER')
        if referer and ('product_detail' in referer or 'product_page' in referer):
            return redirect(referer)
        
        return redirect('product_page')
        
    except Exception as e:
        print(f"Error adding to cart: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        error_message = 'Sorry, something went wrong. Please try again later.'
        
        # Handle AJAX response
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': error_message
            }, status=500)
        
        # Handle non-AJAX response
        messages.error(request, error_message)
        return redirect('product_page')

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def update_quantity(request, cart_item_id):
    try:
        cart_item = get_object_or_404(Cart, id=cart_item_id, user=request.user)
        action = request.POST.get('action')
        
        # Get current quantity
        current_quantity = cart_item.quantity
        
        # Update quantity based on action
        if action == 'increment':
            new_quantity = current_quantity + 1
        elif action == 'decrement':
            new_quantity = current_quantity - 1
        else:
            # If no valid action is provided, try to get direct quantity
            try:
                new_quantity = int(request.POST.get('quantity', current_quantity))
            except ValueError:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid quantity value'
                })
        
        # Validate quantity
        if new_quantity <= 0:
            return JsonResponse({
                'status': 'error',
                'message': 'Quantity must be greater than 0'
            })
            
        if new_quantity > MAX_QUANTITY_PER_ITEM:
            return JsonResponse({
                'status': 'error',
                'message': f'You can only have up to {MAX_QUANTITY_PER_ITEM} copies of this item in your cart.'
            })
            
        if new_quantity > cart_item.product.stock:
            return JsonResponse({
                'status': 'error',
                'message': f'Only {cart_item.product.stock} copies are available in stock.'
            })
        
        # Update quantity and save
        cart_item.quantity = new_quantity
        cart_item.save()
        
        # Calculate new totals
        cart_items = Cart.objects.filter(user=request.user)
        subtotal = sum(item.total_price for item in cart_items)
        discount = round((subtotal * DISCOUNT_PERCENTAGE) / 100)
        delivery_charge = DELIVERY_CHARGE if cart_items else 0
        total = subtotal - discount + delivery_charge
        
        # Check if all items are valid for checkout
        all_items_valid = all(item.is_valid_for_checkout for item in cart_items)
        
        return JsonResponse({
            'status': 'success',
            'message': 'Quantity updated successfully',
            'quantity': new_quantity,
            'item_total': cart_item.total_price,
            'subtotal': subtotal,
            'discount': discount,
            'delivery_charge': delivery_charge,
            'total': total,
            'stock': cart_item.product.stock,
            'all_items_valid': all_items_valid,
            'cart_count': cart_items.count()
        })
        
    except Cart.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Cart item not found'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        })

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def remove_from_cart(request, cart_item_id):
    try:
        cart_item = get_object_or_404(Cart, id=cart_item_id, user=request.user)
        cart_item.delete()
        
        # Calculate new totals
        cart_items = Cart.objects.filter(user=request.user)
        subtotal = sum(item.total_price for item in cart_items)
        discount = round((subtotal * DISCOUNT_PERCENTAGE) / 100)
        delivery_charge = DELIVERY_CHARGE if cart_items else 0
        total = subtotal - discount + delivery_charge
        
        # Check if all items are valid for checkout
        all_items_valid = all(item.is_valid_for_checkout for item in cart_items) if cart_items.exists() else False
        
        return JsonResponse({
            'status': 'success',
            'message': 'Item removed from cart',
            'subtotal': subtotal,
            'discount': discount,
            'delivery_charge': delivery_charge,
            'total': total,
            'all_items_valid': all_items_valid,
            'cart_count': cart_items.count()
        })
        
    except Cart.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Cart item not found'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        })

@login_required(login_url='login_page')
def order_placed(request):
    return render(request, 'order_placed.html')

@login_required(login_url='login_page')
def buy_now(request, product_id):
    try:
        product = get_object_or_404(Product, id=product_id)
        quantity = int(request.POST.get('quantity', 1))
        
        # Check if product is available
        if product.status != 'active':
            return JsonResponse({
                'status': 'error',
                'message': f'Sorry, {product.title} is currently not available for purchase.'
            })
        
        if not product.category.is_active:
            return JsonResponse({
                'status': 'error',
                'message': f'Sorry, {product.title} is currently not available in this category.'
            })
        
        if product.stock <= 0:
            return JsonResponse({
                'status': 'error',
                'message': f'Sorry, {product.title} is currently out of stock.'
            })

        if quantity > MAX_QUANTITY_PER_ITEM:
            return JsonResponse({
                'status': 'error',
                'message': f'You can only purchase up to {MAX_QUANTITY_PER_ITEM} copies of {product.title}.'
            })

        if quantity > product.stock:
            return JsonResponse({
                'status': 'error',
                'message': f'Only {product.stock} copies of {product.title} are available in stock.'
            })

        # Clear existing cart
        Cart.objects.filter(user=request.user).delete()
        
        # Create new cart item
        Cart.objects.create(
            user=request.user,
            product=product,
            quantity=quantity
        )
        
        return JsonResponse({
            'status': 'success',
            'redirect_url': reverse('cart_section:checkout')
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': 'An error occurred while processing your request.'
        })

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def apply_coupon(request):
    try:
        coupon_code = request.POST.get('coupon_code')
        if not coupon_code:
            return JsonResponse({
                'status': 'error',
                'message': 'Please enter a coupon code'
            })
        
        # Get cart items
        cart_items = Cart.objects.filter(user=request.user)
        if not cart_items.exists():
            return JsonResponse({
                'status': 'error',
                'message': 'Your cart is empty'
            })
        
        # Calculate subtotal
        subtotal = sum(item.total_price for item in cart_items)
        
        # Try to find a valid coupon (user-specific or global)
        try:
            coupon = Coupon.objects.filter(
                code__iexact=coupon_code,  # Case-insensitive matching
                is_active=True,
                expiry_date__gt=timezone.now()
            ).filter(
                Q(user=request.user) | Q(user__isnull=True)
            ).first()
            
            if not coupon:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid coupon code or coupon has expired'
                })
            
            # Check if the user has already used this coupon
            if CouponUsage.objects.filter(coupon=coupon, user=request.user).exists():
                return JsonResponse({
                    'status': 'error',
                    'message': 'This coupon has already been used and cannot be applied again'
                })
            
            # Check minimum purchase amount
            if subtotal < coupon.min_purchase_amount:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Minimum purchase amount of ₹{coupon.min_purchase_amount} required for this coupon'
                })
            
            # Calculate discount
            if coupon.discount_percentage:
                discount = round((subtotal * coupon.discount_percentage) / 100)
                discount_text = f"{coupon.discount_percentage}%"
            else:
                discount = coupon.discount_amount
                discount_text = f"₹{discount}"
            
            # Calculate new total
            new_total = subtotal - discount + DELIVERY_CHARGE
            
            # Ensure total is not negative
            if new_total < 0:
                new_total = 0
            
            # Store coupon in session
            request.session['coupon_code'] = coupon_code
            request.session['coupon_discount'] = float(discount)
            
            return JsonResponse({
                'status': 'success',
                'message': f'Coupon applied successfully! {discount_text} discount',
                'discount': float(discount),
                'discount_text': f'₹{discount}',
                'new_total': float(new_total)
            })
        except Exception as e:
            print(f"Error applying coupon: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return JsonResponse({
                'status': 'error',
                'message': f'An error occurred: {str(e)}'
            })
        
    except Exception as e:
        print(f"Error applying coupon: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return JsonResponse({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        })

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def remove_coupon(request):
    try:
        # Get cart items to calculate subtotal
        cart_items = Cart.objects.filter(user=request.user)
        if not cart_items.exists():
            return JsonResponse({
                'status': 'error',
                'message': 'Your cart is empty'
            })
        
        # Calculate totals without coupon
        subtotal = sum(item.total_price for item in cart_items)
        discount = round((subtotal * DISCOUNT_PERCENTAGE) / 100)
        total = subtotal - discount + DELIVERY_CHARGE
        
        # Remove coupon from session
        if 'coupon_code' in request.session:
            del request.session['coupon_code']
        if 'coupon_discount' in request.session:
            del request.session['coupon_discount']
        
        return JsonResponse({
            'status': 'success',
            'message': 'Coupon removed successfully',
            'new_total': float(total)
        })
    
    except Exception as e:
        print(f"Error removing coupon: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return JsonResponse({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        })

@login_required(login_url='login_page')
def retry_payment(request, order_id):
    """
    View to retry payment for a pending order.
    """
    try:
        # Get the order with the given ID
        order = get_object_or_404(Order, order_id=order_id, user=request.user)
        
        # Print debug info
        print(f"Retry payment requested for order: {order_id}, status: {order.status}, payment_status: {order.payment_status}")
        
        # Verify that the order is eligible for retry
        if order.status not in ['PENDING', 'CONFIRMED'] or order.payment_status == 'PAID':
            messages.error(request, f'This order (status: {order.status}, payment: {order.payment_status}) is not eligible for payment retry. Only pending or confirmed orders with unpaid status can be retried.')
            return redirect('user_profile:order_detail', order_id=order_id)
        
        # For retry payments, force online payment (RAZORPAY) only
        order.payment_method = 'RAZORPAY'
        order.save()
        
        # Store order details in session for payment process
        request.session['retry_order_id'] = order.order_id
        request.session['retry_order_total'] = str(order.total)
        request.session['is_retry_payment'] = True  # Add flag to indicate retry payment
        
        # If this order had a coupon applied, try to re-apply it
        try:
            coupon_usage = CouponUsage.objects.filter(order=order).first()
            if coupon_usage and coupon_usage.coupon:
                request.session['coupon_code'] = coupon_usage.coupon.code
                
                # Calculate coupon discount
                if coupon_usage.coupon.discount_percentage:
                    coupon_discount = round((order.subtotal * coupon_usage.coupon.discount_percentage) / 100)
                else:
                    coupon_discount = coupon_usage.coupon.discount_amount
                    
                request.session['coupon_discount'] = coupon_discount
        except Exception as e:
            # Log error but continue
            print(f"Error retrieving coupon for order {order_id}: {str(e)}")
        
        # Redirect directly to payment page for retry payments (skip checkout)
        messages.success(request, 'You will now be redirected to the payment gateway to complete your purchase.')
        return redirect('online_payment:initiate_payment', order_id=order.order_id)
        
    except Exception as e:
        print(f"Error in retry_payment: {str(e)}")
        import traceback
        print(traceback.format_exc())
        messages.error(request, f'Error processing payment retry: {str(e)}')
        return redirect('user_profile:order_detail', order_id=order_id)

def handle_undefined_checkout(request, undefined_path):
    """
    Handle undefined checkout URLs (like /checkout/undefined) and redirect to order_placed
    """
    # Log the occurrence for monitoring
    print(f"Undefined checkout URL accessed: {undefined_path}")
    
    # Check if there's a current order in session
    if 'current_order_id' in request.session:
        order_id = request.session['current_order_id']
        try:
            order = Order.objects.get(order_id=order_id, user=request.user)
            
            # For Razorpay orders, redirect to payment success
            if order.payment_method == 'RAZORPAY':
                return redirect('online_payment:payment_success', order_id=order_id)
        except:
            pass
    
    # Default fallback to order placed page
    return redirect('cart_section:order_placed')