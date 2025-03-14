from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from cart_section.models import Order, Cart
from admin_side.models import Coupon, CouponUsage, ReferralHistory
import razorpay
import json
import hmac
import hashlib
import logging

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize Razorpay client
# You'll need to add these settings to your settings.py file
# RAZORPAY_KEY_ID = 'your_key_id'
# RAZORPAY_KEY_SECRET = 'your_key_secret'
try:
    razorpay_client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
except Exception as e:
    logger.error(f"Failed to initialize Razorpay client: {str(e)}")
    razorpay_client = None

@login_required(login_url='login_page')
def initiate_payment(request, order_id):
    """
    Initiate a Razorpay payment for the given order
    """
    try:
        # Get the order
        order = get_object_or_404(Order, order_id=order_id, user=request.user)
        
        # Check if order is already paid
        if order.payment_status == 'PAID':
            messages.info(request, 'This order has already been paid for')
            return redirect('cart_section:order_placed')
        
        # Create a Razorpay order
        razorpay_order = razorpay_client.order.create({
            'amount': int(order.total * 100),  # Amount in paise
            'currency': 'INR',
            'receipt': order.order_id,
            'payment_capture': '1'  # Auto-capture payment
        })
        
        # Save Razorpay order ID to your order
        order.razorpay_order_id = razorpay_order['id']
        order.save()
        
        # Prepare context for the payment page
        context = {
            'order': order,
            'razorpay_order_id': razorpay_order['id'],
            'razorpay_merchant_key': settings.RAZORPAY_KEY_ID,
            'razorpay_amount': int(order.total * 100),
            'currency': 'INR',
            'callback_url': request.build_absolute_uri(reverse('online_payment:payment_callback')),
            'customer_name': request.user.get_full_name() or request.user.username,
            'customer_email': request.user.email,
            'customer_phone': order.address.phone_number,
        }
        
        return render(request, 'payment.html', context)
    
    except Exception as e:
        logger.error(f"Error initiating payment: {str(e)}")
        messages.error(request, 'Failed to initiate payment. Please try again.')
        return redirect('cart_section:checkout')

@csrf_exempt
def payment_callback(request):
    """
    Handle the callback from Razorpay after payment
    """
    if request.method == 'POST':
        try:
            # Get payment data
            payment_data = request.POST
            logger.info(f"Received payment callback data: {payment_data}")
            
            # Verify signature
            razorpay_payment_id = payment_data.get('razorpay_payment_id', '')
            razorpay_order_id = payment_data.get('razorpay_order_id', '')
            razorpay_signature = payment_data.get('razorpay_signature', '')
            
            logger.info(f"Payment ID: {razorpay_payment_id}")
            logger.info(f"Order ID: {razorpay_order_id}")
            
            # Create signature for verification
            params_dict = {
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_order_id': razorpay_order_id,
                'razorpay_signature': razorpay_signature
            }
            
            try:
                # Verify signature
                is_valid_signature = razorpay_client.utility.verify_payment_signature(params_dict)
                logger.info(f"Signature verification result: {is_valid_signature}")
            except Exception as e:
                logger.error(f"Error verifying signature: {str(e)}")
                is_valid_signature = False
            
            if is_valid_signature:
                # Payment successful
                # Find the order by Razorpay order ID
                try:
                    order = Order.objects.get(razorpay_order_id=razorpay_order_id)
                    logger.info(f"Found order: {order.order_id}")
                    
                    try:
                        # Verify payment status with Razorpay
                        payment = razorpay_client.payment.fetch(razorpay_payment_id)
                        logger.info(f"Payment status from Razorpay: {payment.get('status')}")
                        
                        if payment.get('status') == 'captured':
                            # Update order payment details
                            order.payment_id = razorpay_payment_id
                            order.payment_status = 'PAID'
                            order.payment_method = 'RAZORPAY'
                            order.status = 'CONFIRMED'  # Update order status
                            order.save()
                            logger.info(f"Order {order.order_id} updated as paid and confirmed")
                            
                            # Process referral reward if applicable
                            process_referral_reward(order)
                            
                            # Clear cart and session data
                            Cart.objects.filter(user=order.user).delete()
                            if 'coupon_code' in request.session:
                                del request.session['coupon_code']
                            if 'coupon_discount' in request.session:
                                del request.session['coupon_discount']
                            
                            logger.info("Redirecting to order placed page")
                            return redirect('cart_section:order_placed')
                        else:
                            logger.error(f"Payment not captured. Status: {payment.get('status')}")
                            order.payment_status = 'FAILED'
                            order.save()
                            return redirect('online_payment:payment_failure')
                    except Exception as e:
                        logger.error(f"Error fetching payment status: {str(e)}")
                        return redirect('online_payment:payment_failure')
                
                except Order.DoesNotExist:
                    logger.error(f"Order not found for Razorpay order ID: {razorpay_order_id}")
                    return redirect('online_payment:payment_failure')
                except Exception as e:
                    logger.error(f"Error processing payment: {str(e)}")
                    return redirect('online_payment:payment_failure')
            else:
                logger.error("Invalid signature")
                return redirect('online_payment:payment_failure')
        
        except Exception as e:
            logger.error(f"Error processing payment callback: {str(e)}")
            return redirect('online_payment:payment_failure')
    
    return redirect('cart_section:checkout')

@login_required(login_url='login_page')
def payment_success(request, order_id):
    """
    Display payment success page
    """
    try:
        order = get_object_or_404(Order, order_id=order_id, user=request.user)
        
        # Clear cart
        Cart.objects.filter(user=request.user).delete()
        
        # Clear coupon from session
        if 'coupon_code' in request.session:
            del request.session['coupon_code']
        if 'coupon_discount' in request.session:
            del request.session['coupon_discount']
        
        context = {
            'order': order,
        }
        
        return render(request, 'payment_success.html', context)
    
    except Exception as e:
        logger.error(f"Error displaying payment success page: {str(e)}")
        messages.error(request, 'An error occurred. Please check your orders for status.')
        return redirect('user_profile:orders')

@login_required(login_url='login_page')
def payment_failure(request):
    """
    Display payment failure page
    """
    return render(request, 'payment_failure.html')

def process_referral_reward(order):
    """
    Process referral reward for the order
    """
    try:
        # Check if the user was referred
        referral_history = ReferralHistory.objects.filter(referred_user=order.user).first()
        
        if referral_history and not referral_history.reward_given:
            # Import here to avoid circular import
            from cart_section.views import create_referral_reward_coupon
            
            # Create a coupon as reward
            coupon = create_referral_reward_coupon(
                user=referral_history.referrer,
                order_id=order.order_id
            )
            
            if coupon:
                # Mark referral as rewarded
                referral_history.reward_given = True
                referral_history.save()
                
                # Store the coupon code in the order for reference
                order.notes = f"Referral reward coupon created: {coupon.code}"
                order.save()
    
    except Exception as e:
        logger.error(f"Error processing referral reward: {str(e)}")
