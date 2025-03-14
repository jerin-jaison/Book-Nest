from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.views.decorators.http import require_http_methods
from .models import Cart, Address, Order, OrderItem
from admin_side.models import Product, Coupon, CouponUsage, ReferralHistory
from user_profile.models import Wishlist as ProfileWishlist, WishlistItem, AccountDetails
from user_authentication.models import Wishlist as AuthWishlist
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

MAX_QUANTITY_PER_ITEM = 5  
DELIVERY_CHARGE = 40  # Fixed delivery charge
DISCOUNT_PERCENTAGE = 0  # No default discount
REFERRAL_REWARD_AMOUNT = Decimal('100.00')  # Fixed reward amount of 100 rupees

# Constants
TAX_RATE = Decimal('0.05')  # 5% tax rate

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
            expiry_date=expiry_date
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
    cart_items = Cart.objects.filter(user=request.user).select_related('product')
    
    if not cart_items.exists():
        messages.error(request, 'Your cart is empty')
        return redirect('cart_section:view_cart')
    
    # Check if all items are valid for checkout
    invalid_items = [item for item in cart_items if not item.is_valid_for_checkout]
    if invalid_items:
        messages.error(request, 'Some items in your cart are not available for checkout')
        return redirect('cart_section:view_cart')
    
    # Get user's addresses from AccountDetails
    account_details = AccountDetails.objects.filter(user=request.user).first()
    
    # Get user's addresses from Address model
    addresses = Address.objects.filter(user=request.user).order_by('-is_default', '-created_at')
    
    # Mark addresses that are used in orders
    addresses_with_orders = list(Order.objects.filter(address__in=addresses).values('address').annotate(count=Count('id')))
    addresses_in_use = {item['address']: item['count'] for item in addresses_with_orders}
    
    for address in addresses:
        address.is_used_in_orders = address.id in addresses_in_use
        address.orders_count = addresses_in_use.get(address.id, 0)
    
    # Calculate totals
    subtotal = sum(item.total_price for item in cart_items)
    discount = round((subtotal * DISCOUNT_PERCENTAGE) / 100)
    delivery_charge = DELIVERY_CHARGE
    total_amount = subtotal - discount + delivery_charge
    
    # Check for applied coupon in session
    applied_coupon = request.session.get('coupon_code')
    coupon_discount = 0
    
    if applied_coupon:
        try:
            # Try to find user-specific coupon
            try:
                coupon = Coupon.objects.get(
                    code=applied_coupon,
                    user=request.user,
                    is_active=True,
                    expiry_date__gt=timezone.now()
                )
            except Coupon.DoesNotExist:
                # Try to find global coupon
                coupon = Coupon.objects.get(
                    code=applied_coupon,
                    user__isnull=True,
                    is_active=True,
                    expiry_date__gt=timezone.now()
                )
            
            # Check if the user has already used this coupon
            if coupon.is_used_by_user(request.user):
                # If coupon has been used, remove from session
                if 'coupon_code' in request.session:
                    del request.session['coupon_code']
                if 'coupon_discount' in request.session:
                    del request.session['coupon_discount']
                applied_coupon = None
            else:
                # Calculate coupon discount
                if coupon.discount_percentage:
                    coupon_discount = round((subtotal * coupon.discount_percentage) / 100)
                else:
                    coupon_discount = coupon.discount_amount
                
                # Update total amount
                total_amount = total_amount - coupon_discount
                
                # Ensure total is not negative
                if total_amount < 0:
                    total_amount = 0
            
        except Coupon.DoesNotExist:
            # If coupon no longer valid, remove from session
            if 'coupon_code' in request.session:
                del request.session['coupon_code']
            if 'coupon_discount' in request.session:
                del request.session['coupon_discount']
            applied_coupon = None
    
    # Get eligible coupons for the user
    current_time = timezone.now()
    
    # Get user-specific coupons
    user_coupons = Coupon.objects.filter(
        user=request.user,
        is_active=True,
        expiry_date__gt=current_time,
        min_purchase_amount__lte=subtotal
    ).order_by('-created_at')
    
    # Get global coupons
    global_coupons = Coupon.objects.filter(
        user__isnull=True,
        is_active=True,
        expiry_date__gt=current_time,
        min_purchase_amount__lte=subtotal
    ).order_by('-created_at')
    
    # Combine both types of coupons
    eligible_coupons = list(user_coupons) + list(global_coupons)
    
    # Filter out coupons that the user has already used
    eligible_coupons = [coupon for coupon in eligible_coupons if not coupon.is_used_by_user(request.user)]
    
    # Calculate potential discount for each coupon
    for coupon in eligible_coupons:
        if coupon.discount_percentage:
            coupon.potential_discount = round((subtotal * coupon.discount_percentage) / 100)
            coupon.discount_display = f"{coupon.discount_percentage}% off"
        else:
            coupon.potential_discount = coupon.discount_amount
            coupon.discount_display = f"₹{coupon.discount_amount} off"
    
    # Sort coupons by potential discount (highest first) and mark the best value coupon
    eligible_coupons.sort(key=lambda x: x.potential_discount, reverse=True)
    if eligible_coupons:
        eligible_coupons[0].is_best_value = True
    
    context = {
        'cart_items': cart_items,
        'account_details': account_details,
        'addresses': addresses,
        'subtotal': subtotal,
        'discount': discount,
        'discount_percentage': DISCOUNT_PERCENTAGE,
        'delivery_charge': delivery_charge,
        'total_amount': total_amount,
        'applied_coupon': applied_coupon,
        'coupon_discount': coupon_discount,
        'eligible_coupons': eligible_coupons,
        'now': current_time,  # Pass current time for offer validation
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
        with transaction.atomic():
            payment_method = request.POST.get('payment_method', 'COD')
            
            # For COD orders, handle separately with guaranteed success
            if payment_method == 'COD':
                address_id = request.POST.get('selected_address_id')
                coupon_code = request.POST.get('coupon_code')
                
                # Get address
                address = Address.objects.get(id=address_id, user=request.user)
                
                # Get cart items
                cart_items = Cart.objects.filter(user=request.user)
                
                # Calculate totals
                subtotal = sum(item.total_price for item in cart_items)
                discount = round((subtotal * DISCOUNT_PERCENTAGE) / 100)
                total = subtotal - discount + DELIVERY_CHARGE
                
                # Apply coupon if provided
                coupon_discount = 0
                coupon = None
                if coupon_code:
                    try:
                        # Try to find user-specific coupon
                        try:
                            coupon = Coupon.objects.get(
                                code=coupon_code,
                                user=request.user,
                                is_active=True,
                                expiry_date__gt=timezone.now()
                            )
                        except Coupon.DoesNotExist:
                            # Try to find global coupon
                            coupon = Coupon.objects.get(
                                code=coupon_code,
                                user__isnull=True,
                                is_active=True,
                                expiry_date__gt=timezone.now()
                            )
                        
                        # Calculate coupon discount
                        if coupon.discount_percentage:
                            coupon_discount = round((subtotal * coupon.discount_percentage) / 100)
                        else:
                            coupon_discount = coupon.discount_amount
                        
                        # Update total
                        total = total - coupon_discount
                        
                        # Ensure total is not negative
                        if total < 0:
                            total = 0
                        
                    except Coupon.DoesNotExist:
                        pass  # Ignore if coupon doesn't exist
                
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
            
            # For online payment, proceed with regular validation
            else:
                address_id = request.POST.get('selected_address_id')
                if not address_id:
                    raise ValueError('Please select a shipping address')
                
                # Get address
                try:
                    address = Address.objects.get(id=address_id, user=request.user)
                except Address.DoesNotExist:
                    raise ValueError('Selected address not found')
                
                # Get cart items
                cart_items = Cart.objects.filter(user=request.user)
                if not cart_items.exists():
                    raise ValueError('Your cart is empty')
                
                # Check if all items are valid for checkout
                invalid_items = [item for item in cart_items if not item.is_valid_for_checkout]
                if invalid_items:
                    raise ValueError('Some items in your cart are not available for checkout')
                
                # Calculate totals
                subtotal = sum(item.total_price for item in cart_items)
                discount = round((subtotal * DISCOUNT_PERCENTAGE) / 100)
                total = subtotal - discount + DELIVERY_CHARGE
                
                # Apply coupon if provided
                coupon_discount = 0
                coupon = None
                coupon_code = request.POST.get('coupon_code')
                if coupon_code:
                    try:
                        # First try to find a user-specific coupon
                        try:
                            coupon = Coupon.objects.get(
                                code=coupon_code,
                                user=request.user,
                                is_active=True,
                                expiry_date__gt=timezone.now()
                            )
                        except Coupon.DoesNotExist:
                            # If not found, try to find a global coupon (user=None)
                            coupon = Coupon.objects.get(
                                code=coupon_code,
                                user__isnull=True,
                                is_active=True,
                                expiry_date__gt=timezone.now()
                            )
                        
                        # Check if the user has already used this coupon
                        if coupon.is_used_by_user(request.user):
                            raise ValueError('You have already used this coupon')
                        
                        # Check minimum purchase amount
                        if subtotal < coupon.min_purchase_amount:
                            raise ValueError(f'Minimum purchase amount of ₹{coupon.min_purchase_amount} required for this coupon')
                        
                        # Calculate coupon discount
                        if coupon.discount_percentage:
                            coupon_discount = round((subtotal * coupon.discount_percentage) / 100)
                        else:
                            coupon_discount = coupon.discount_amount
                        
                        # Update total
                        total = total - coupon_discount
                        
                        # Ensure total is not negative
                        if total < 0:
                            total = 0
                        
                    except Coupon.DoesNotExist:
                        pass  # Ignore if coupon doesn't exist
                
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
                    status='PENDING'  # Keep status as PENDING until payment is confirmed
                )
                
                # Create order items and update stock
                for cart_item in cart_items:
                    product = cart_item.product
                    
                    # Verify stock one last time
                    if product.stock < cart_item.quantity:
                        raise ValueError(f'Not enough stock for {product.title}')
                    
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
                
                # For online payment, redirect to payment page
                return JsonResponse({
                    'status': 'success',
                    'message': 'Order placed successfully',
                    'order_id': order.order_id,
                    'redirect_url': reverse('online_payment:initiate_payment', args=[order.order_id])
                })
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': 'An error occurred while placing your order'
        })

@login_required(login_url='login_page')
@require_http_methods(["POST"])
def add_to_cart(request, product_id):
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
                'message': f'You can only add up to {MAX_QUANTITY_PER_ITEM} copies of {product.title} to your cart.'
            })

        if quantity > product.stock:
            return JsonResponse({
                'status': 'error',
                'message': f'Only {product.stock} copies of {product.title} are available in stock.'
            })

        with transaction.atomic():
            cart_item, created = Cart.objects.get_or_create(
                user=request.user,
                product=product,
                defaults={'quantity': quantity}
            )
            
            if not created:
                new_quantity = cart_item.quantity + quantity
                if new_quantity > MAX_QUANTITY_PER_ITEM:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'You already have {cart_item.quantity} copies of {product.title} in your cart. Maximum allowed is {MAX_QUANTITY_PER_ITEM}.'
                    })
                
                if new_quantity > product.stock:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Cannot add more copies of {product.title}. Only {product.stock} available in stock.'
                    })
                
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
            message = f'{product.title} has been added to your cart.'
        else:
            message = f'Updated quantity of {product.title} in your cart to {new_quantity}.'
            
        return JsonResponse({
            'status': 'success',
            'cart_count': cart_count,
            'message': message
        })
    except Exception as e:
        print(f"Error adding to cart: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': 'Sorry, something went wrong. Please try again later.'
        }, status=500)

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
        
        # Get cart items to calculate subtotal
        cart_items = Cart.objects.filter(user=request.user)
        if not cart_items.exists():
            return JsonResponse({
                'status': 'error',
                'message': 'Your cart is empty'
            })
        
        subtotal = sum(item.total_price for item in cart_items)
        
        # Check if coupon exists and is valid
        try:
            # First try to find a user-specific coupon
            try:
                coupon = Coupon.objects.get(
                    code=coupon_code,
                    user=request.user,
                    is_active=True,
                    expiry_date__gt=timezone.now()
                )
            except Coupon.DoesNotExist:
                # If not found, try to find a global coupon (user=None)
                coupon = Coupon.objects.get(
                    code=coupon_code,
                    user__isnull=True,
                    is_active=True,
                    expiry_date__gt=timezone.now()
                )
            
            # Check if the user has already used this coupon
            if coupon.is_used_by_user(request.user):
                return JsonResponse({
                    'status': 'error',
                    'message': 'You have already used this coupon'
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
            
        except Coupon.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid coupon code or coupon has expired'
            })
    
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
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
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        })