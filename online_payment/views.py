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

def verify_payment_signature(data):
    """
    Verify the payment signature received from Razorpay
    """
    try:
        razorpay_payment_id = data.get('razorpay_payment_id', '')
        razorpay_order_id = data.get('razorpay_order_id', '')
        razorpay_signature = data.get('razorpay_signature', '')
        
        # Create signature for verification
        params_dict = {
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_order_id': razorpay_order_id,
            'razorpay_signature': razorpay_signature
        }
        
        # Verify the payment signature
        return razorpay_client.utility.verify_payment_signature(params_dict)
    
    except Exception as e:
        logger.error(f"Error verifying payment signature: {str(e)}")
        return False

@csrf_exempt
def payment_callback(request):
    try:
        # Get payment data
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_signature = request.POST.get('razorpay_signature')
        
        logger.info(f"Payment callback received: payment_id={razorpay_payment_id}, order_id={razorpay_order_id}")
        
        # Verify signature
        if not verify_payment_signature(request.POST):
            logger.error("Payment signature verification failed")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid payment signature',
                'redirect_url': reverse('online_payment:payment_failure')
            }, status=400)
            
        # Find the order using razorpay_order_id
        try:
            order = Order.objects.get(razorpay_order_id=razorpay_order_id)
            logger.info(f"Found order: {order.order_id}, status: {order.status}, payment_status: {order.payment_status}")
        except Order.DoesNotExist:
            logger.error(f"Order not found for razorpay_order_id: {razorpay_order_id}")
            return JsonResponse({
                'status': 'error',
                'message': 'Order not found',
                'redirect_url': reverse('online_payment:payment_failure')
            }, status=400)
        
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
            
            logger.info(f"Order {order.order_id} marked as PAID and CONFIRMED")
            
            # Clear session data
            if 'current_order_id' in request.session:
                del request.session['current_order_id']
            if 'retry_order_id' in request.session:
                del request.session['retry_order_id']
            if 'retry_order_total' in request.session:
                del request.session['retry_order_total']
            if 'is_retry_payment' in request.session:
                del request.session['is_retry_payment']
            
            # Process referral rewards if applicable
            try:
                referral_history = ReferralHistory.objects.filter(
                    referred_user=order.user,
                    reward_status='PENDING'
                ).first()
                
                if referral_history:
                    referral_history.reward_status = 'COMPLETED'
                    referral_history.save()
                    logger.info(f"Referral reward completed for user {order.user.username}")
            except Exception as e:
                logger.error(f"Error processing referral reward: {str(e)}")
            
            # Redirect to success page
            success_url = reverse('online_payment:payment_success', args=[order.order_id])
            logger.info(f"Redirecting to success page: {success_url}")
            
            return JsonResponse({
                'status': 'success',
                'redirect_url': success_url
            })
        else:
            # Payment not captured
            order.payment_status = 'FAILED'
            order.save()
            
            logger.error(f"Payment failed. Razorpay status: {payment.get('status')}")
            
            return JsonResponse({
                'status': 'error',
                'message': 'Payment failed',
                'redirect_url': reverse('online_payment:payment_failure') + f'?order_id={order.order_id}'
            }, status=400)
            
    except Exception as e:
        logger.error(f"Error in payment callback: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'redirect_url': reverse('online_payment:payment_failure')
        }, status=500)

@login_required(login_url='login_page')
def payment_success(request, order_id):
    """
    Display payment success page
    """
    try:
        order = get_object_or_404(Order, order_id=order_id, user=request.user)
        
        logger.info(f"Payment success page for order: {order_id}")
        
        # Clear cart
        Cart.objects.filter(user=request.user).delete()
        
        # Clear coupon from session
        if 'coupon_code' in request.session:
            del request.session['coupon_code']
        if 'coupon_discount' in request.session:
            del request.session['coupon_discount']
        
        # Check if this was a retry payment
        is_retry = request.session.get('is_retry_payment', False)
        
        context = {
            'order': order,
            'is_retry': is_retry,
        }
        
        # Clear retry flag
        if 'is_retry_payment' in request.session:
            del request.session['is_retry_payment']
        
        # Redirect to user profile after 3 seconds
        context['redirect_url'] = reverse('user_profile:order_detail', args=[order_id])
        context['countdown'] = 3
        
        return render(request, 'payment_success.html', context)
    
    except Exception as e:
        logger.error(f"Error displaying payment success page: {str(e)}")
        messages.error(request, 'An error occurred. Please check your orders for status.')
        return redirect('user_profile:orders_list')

@login_required(login_url='login_page')
def payment_failure(request):
    """
    Display payment failure page
    """
    try:
        order_id = request.GET.get('order_id')
        if order_id:
            # If order_id is provided, update the order status
            try:
                order = Order.objects.get(order_id=order_id, user=request.user)
                if order.payment_status == 'PENDING':
                    order.payment_status = 'FAILED'
                    order.save()
                    logger.info(f"Order {order_id} marked as payment failed")
            except Order.DoesNotExist:
                logger.error(f"Order not found for ID: {order_id}")
        
        return render(request, 'payment_failure.html')
    
    except Exception as e:
        logger.error(f"Error displaying payment failure page: {str(e)}")
        messages.error(request, 'An error occurred. Please check your orders for status.')
        return redirect('user_profile:orders_list')

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
