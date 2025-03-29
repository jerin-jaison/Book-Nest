from django.shortcuts import render, redirect, get_object_or_404
from .models import AccountDetails, WishlistItem
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
import random
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
import os
import re
from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from cart_section.models import Order, OrderItem, Product
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.urls import reverse
from user_wallet.models import Wallet, WalletTransaction
from user_wallet.views import deduct_referral_reward
from django.template.loader import get_template
from xhtml2pdf import pisa
from io import BytesIO
import datetime
from admin_side.models import Coupon, ReferralCode, ReferralHistory
from decimal import Decimal
from admin_side.models import CouponUsage
from django.db.models import Exists, OuterRef

def validate_image_file(image):
    # Check if file is an image
    if not image:
        return False
    
    # Get file extension
    file_ext = os.path.splitext(image.name)[1].lower()
    
    # List of valid image extensions
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif']
    
    # Check if extension is valid
    if file_ext not in valid_extensions:
        return False
    
    # Check file size (max 5MB)
    if image.size > 5 * 1024 * 1024:  # 5MB in bytes
        return False
    
    return True

def validate_phone_number(phone):
    """
    Validates phone number format.
    Rules:
    1. Must be 10 digits
    2. Must start with 6-9
    3. Must be all numbers
    """
    # Remove any spaces or special characters
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    
    # Check if it's a valid Indian mobile number
    pattern = r'^[6-9]\d{9}$'
    if not re.match(pattern, phone):
        return False, "Invalid phone number. Please enter a valid 10-digit mobile number starting with 6-9"
    
    return True, "Valid phone number"

def generate_otp():
    return ''.join(random.choices('0123456789', k=6))

@login_required(login_url='login_page')
def profile_view(request):
    account_details = AccountDetails.objects.filter(user=request.user).first()
    if not account_details:
        account_details = AccountDetails.objects.create(
            user=request.user,
            first_name=request.user.first_name,
            last_name=request.user.last_name,
            email=request.user.email,
            phone='',
            address='',
            email_verified=True
        )
    
    # Get recent orders for the user
    orders = Order.objects.filter(user=request.user).order_by('-created_at')[:5]  # Get last 5 orders
    
    context = {
        'account_details': account_details,
        'orders': orders
    }
    return render(request, 'profile.html', context)

@login_required(login_url='login_page')
def edit_profile(request):
    account_details = AccountDetails.objects.filter(user=request.user).first()
    if not account_details:
        account_details = AccountDetails.objects.create(
            user=request.user,
            first_name=request.user.first_name,
            last_name=request.user.last_name,
            email=request.user.email,
            phone='',
            address='',
            email_verified=True
        )
    
    if request.method == "POST":
        firstName = request.POST.get('firstName')
        lastName = request.POST.get('lastName')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        profile_image = request.FILES.get('profile_image')
        verify_email = request.POST.get('verify_email') == 'true'
        
        # Validate phone number
        if phone:
            is_valid, message = validate_phone_number(phone)
            if not is_valid:
                messages.error(request, message)
                context = {'account_details': account_details}
                return render(request, 'edit_profile.html', context)
            
            # Check if phone number is already in use by another user
            if AccountDetails.objects.filter(phone=phone).exclude(user=request.user).exists():
                messages.error(request, 'This phone number is already registered with another account.')
                context = {'account_details': account_details}
                return render(request, 'edit_profile.html', context)
        
        # Validate profile image if one was uploaded
        if profile_image:
            if not validate_image_file(profile_image):
                messages.error(request, 'Invalid image file. Please upload a JPEG, PNG, or GIF file under 5MB.')
                context = {'account_details': account_details}
                return render(request, 'edit_profile.html', context)
        
        # Store form data in session for persistence
        request.session['profile_data'] = {
            'firstName': firstName,
            'lastName': lastName,
            'phone': phone,
            'address': address
        }
        
        # Check if email is being changed or needs verification
        if email != request.user.email or (verify_email and not account_details.email_verified):
            # Check if email already exists
            if User.objects.filter(email=email).exclude(id=request.user.id).exists() or AccountDetails.objects.filter(email=email, email_verified=True).exclude(user=request.user).exists():
                messages.error(request, 'This email address is already in use.')
                context = {'account_details': account_details}
                return render(request, 'edit_profile.html', context)

            otp = generate_otp()
            account_details.email_otp = otp
            account_details.email_otp_timestamp = timezone.now()
            account_details.pending_email = email  # Store the pending email
            account_details.save()
            
            # Send OTP email without try-except
            subject = 'BookNest - Verify your email'
            message = f'''
Hello,

Your verification code for BookNest is: {otp}

This code will expire in 10 minutes.

If you did not request this code, please ignore this email.

Best regards,
BookNest Team
'''
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            print(f"OTP email sent successfully to {email} and the otp is {otp}")
            
            # Store the new email in session for verification
            request.session['new_email'] = email
            messages.info(request, 'Please verify your email address. A verification code has been sent.')
            return redirect('user_profile:verify_email_otp')
        
        # If no email change, update everything
        return update_profile_data(request, account_details, firstName, lastName, email, phone, address, profile_image)
    
    context = {'account_details': account_details}
    return render(request, 'edit_profile.html', context)

def update_profile_data(request, account_details, firstName, lastName, email, phone, address, profile_image=None):
    """Helper function to update profile data"""
    # Update user model
    request.user.first_name = firstName
    request.user.last_name = lastName
    if email == request.user.email or account_details.email_verified:
        request.user.email = email
    request.user.save()
    
    # Update AccountDetails
    account_details.first_name = firstName
    account_details.last_name = lastName
    account_details.phone = phone
    account_details.address = address
    if profile_image:  # Save the profile image if one was uploaded
        account_details.profile_image = profile_image
    account_details.save()
    
    # Clear session data
    if 'profile_data' in request.session:
        del request.session['profile_data']
    
    messages.success(request, 'Profile updated successfully!')
    return redirect('user_profile:profile')

@login_required(login_url='login_page')
def verify_email_otp(request):
    account_details = AccountDetails.objects.filter(user=request.user).first()
    new_email = request.session.get('new_email')
    profile_data = request.session.get('profile_data', {})
    
    if not account_details or not new_email or account_details.pending_email != new_email:
        messages.error(request, 'Invalid verification attempt!')
        return redirect('user_profile:profile')
    
    if request.method == "POST":
        otp = request.POST.get('otp')
        print(otp)
        
        # Check if email is still available
        if User.objects.filter(email=new_email).exists() or AccountDetails.objects.filter(email=new_email, email_verified=True).exists():
            messages.error(request, 'This email address is no longer available. Please try a different email.')
            return redirect('user_profile:edit_profile')
        
        # Check if OTP is valid and not expired (10 minutes)
        if (account_details.email_otp == otp and 
            account_details.email_otp_timestamp and 
            account_details.email_otp_timestamp > timezone.now() - timedelta(minutes=10)):
            
            account_details.email_otp = None
            account_details.email_otp_timestamp = None

            # Update email and mark as verified
            account_details.email = new_email
            account_details.email_verified = True
            account_details.pending_email = None  # Clear the pending email
            
            # Update the rest of the profile data
            if profile_data:
                account_details.first_name = profile_data.get('firstName', account_details.first_name)
                account_details.last_name = profile_data.get('lastName', account_details.last_name)
                account_details.phone = profile_data.get('phone', account_details.phone)
                account_details.address = profile_data.get('address', account_details.address)
            
            account_details.save()
            
            # Update user model
            request.user.email = new_email
            if profile_data:
                request.user.first_name = profile_data.get('firstName', request.user.first_name)
                request.user.last_name = profile_data.get('lastName', request.user.last_name)
            request.user.save()
            
            # Clear session data
            del request.session['new_email']
            if 'profile_data' in request.session:
                del request.session['profile_data']
            
            messages.success(request, 'Email verified and profile updated successfully!')
            return redirect('user_profile:profile')
        else:
            messages.error(request, 'Invalid or expired verification code!')
    
    context = {
        'new_email': new_email,
        'profile_data': profile_data
    }
    return render(request, 'verify_email_otp.html', context)

@login_required(login_url='login_page')
def address_view(request):
    account_details = AccountDetails.objects.filter(user=request.user).first()
    if not account_details:
        account_details = AccountDetails.objects.create(
            user=request.user,
            first_name=request.user.first_name,
            last_name=request.user.last_name,
            email=request.user.email,
            phone='',
            address='',
            email_verified=True
        )
    
    if request.method == "POST":
        # Update address details
        account_details.house_name = request.POST.get('house_name')
        account_details.landmark = request.POST.get('landmark')
        account_details.city = request.POST.get('city')
        account_details.state = request.POST.get('state')
        account_details.pin_code = request.POST.get('pin_code')
        account_details.country = request.POST.get('country')
        account_details.save()
        
        messages.success(request, 'Address updated successfully!')
        return redirect('user_profile:address')
    
    context = {
        'account_details': account_details
    }
    return render(request, 'address.html', context)

@login_required(login_url='login_page')
def acc_detail(request):
    account_details = AccountDetails.objects.filter(user=request.user).first()
    if not account_details:
        account_details = AccountDetails.objects.create(
            user=request.user,
            first_name=request.user.first_name,
            last_name=request.user.last_name,
            email=request.user.email,
            phone='',
            address='',
            email_verified=True
        )
    context = {
        'account_details': account_details
    }
    return render(request, 'acc_detail.html', context)

@login_required(login_url='login_page')
def change_password(request):
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if not request.user.check_password(current_password):
            messages.error(request, 'Current password is incorrect')
            return render(request, 'change_password.html')
        
        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match')
            return render(request, 'change_password.html')
        
        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long')
            return render(request, 'change_password.html')
        
        request.user.set_password(new_password)
        request.user.save()
        
        # Update session to prevent logout
        update_session_auth_hash(request, request.user)
        
        messages.success(request, 'Password changed successfully')
        return redirect('user_profile:profile')
    
    return render(request, 'change_password.html')

def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get('email')
        print(f"\n[Password Reset] Step 1: Email verification requested for {email}")
        
        # Check if user exists with this email
        user = User.objects.filter(email=email).first()
        if not user:
            print(f"[Password Reset] Error: No user found with email {email}")
            messages.error(request, 'We could not find an account with that email address. Please check and try again.')
            return redirect('user_profile:forgot_password')
            
        print(f"[Password Reset] User found: {user.username}")
            
        # Get or create account details
        account_details = AccountDetails.objects.filter(user=user).first()
        if not account_details:
            print(f"[Password Reset] Creating new account details for {user.username}")
            account_details = AccountDetails.objects.create(
                user=user,
                first_name=user.first_name,
                last_name=user.last_name,
                email=user.email,
                phone='',
                address=''
            )
            
        # Generate and save OTP
        otp = generate_otp()
        print(f"[Password Reset] Generated OTP: {otp} for user {user.username}")
        account_details.email_otp = otp
        account_details.email_otp_timestamp = timezone.now()
        account_details.save()
        
        # Send OTP email without try-except
        subject = 'BookNest - Password Reset Verification'
        message = f'''
Hello {user.first_name if user.first_name else user.username},

You have requested to reset your password. Your verification code is:

{otp}

This code will expire in 10 minutes. If you did not request this code, please ignore this email and make sure you can still login to your account.

Best regards,
BookNest Team
'''
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        print(f"[Password Reset] OTP email sent successfully to {email}")
        
        # Store email in session
        request.session['reset_email'] = email
        messages.success(request, 'A verification code has been sent to your email. Please check your inbox and enter the code below.')
        return render(request, 'forgot_password.html', {'email_verified': True, 'email': email})
    
    return render(request, 'forgot_password.html', {'email_verified': False})

def verify_password_otp(request):
    email = request.session.get('reset_email')
    if not email:
        messages.error(request, 'Invalid verification attempt!')
        return redirect('user_profile:forgot_password')
    
    # Check if user exists with this email
    user = User.objects.filter(email=email).first()
    if not user:
        messages.error(request, 'We could not find an account with that email address. Please try again.')
        return redirect('user_profile:forgot_password')
    
    account_details = AccountDetails.objects.filter(user=user).first()
    if not account_details or not account_details.email_otp:
        messages.error(request, 'Invalid verification attempt!')
        return redirect('user_profile:forgot_password')
    
    if request.method == "POST":
        otp = request.POST.get('otp')
        print(f"[Password Reset] OTP received: {otp}")
        
        if (account_details.email_otp == otp and 
            account_details.email_otp_timestamp and 
            account_details.email_otp_timestamp > timezone.now() - timedelta(minutes=10)):
            
            print(f"[Password Reset] OTP verified successfully for user {user.username}")
            # Mark OTP as verified in session
            request.session['otp_verified'] = True
            messages.success(request, 'Email verified successfully! Please set your new password below.')
            return render(request, 'forgot_password.html', {
                'email_verified': True,
                'otp_verified': True,
                'email': email
            })
        else:
            print("[Password Reset] Error: Invalid or expired OTP")
            if not account_details.email_otp_timestamp or account_details.email_otp_timestamp < timezone.now() - timedelta(minutes=10):
                messages.error(request, 'The verification code has expired. Please request a new one.')
            else:
                messages.error(request, 'Invalid verification code. Please check and try again.')
            return render(request, 'forgot_password.html', {
                'email_verified': True,
                'otp_verified': False,
                'email': email
            })
            
    return redirect('user_profile:forgot_password')

def reset_password(request):
    email = request.session.get('reset_email')
    print(f"\n[Password Reset Debug] Email from session: {email}")
    
    if not email:
        messages.error(request, 'Invalid password reset attempt!')
        return redirect('user_profile:forgot_password')
    
    # Check if user exists with this email
    user = User.objects.filter(email=email).first()
    print(f"[Password Reset Debug] User found: {user.username if user else 'None'}")
    
    if not user:
        messages.error(request, 'We could not find an account with that email address. Please try again.')
        return redirect('user_profile:forgot_password')
    
    account_details = AccountDetails.objects.filter(user=user).first()
    otp_verified = request.session.get('otp_verified')
    print(f"[Password Reset Debug] OTP verified from session: {otp_verified}")
    
    if not account_details or not otp_verified:
        messages.error(request, 'Please verify your email first!')
        return redirect('user_profile:forgot_password')
    
    if request.method == "POST":
        print(f"[Password Reset Debug] Processing POST request")
        
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        print(f"[Password Reset Debug] Password length: {len(new_password) if new_password else 0}")
        
        if new_password != confirm_password:
            print("[Password Reset Debug] Error: Passwords do not match")
            messages.error(request, 'The passwords you entered do not match. Please try again.')
            return render(request, 'forgot_password.html', {
                'email_verified': True,
                'otp_verified': True,
                'email': email
            })
            
        if len(new_password) < 8:
            print("[Password Reset Debug] Error: Password too short")
            messages.error(request, 'Your password must be at least 8 characters long.')
            return render(request, 'forgot_password.html', {
                'email_verified': True,
                'otp_verified': True,
                'email': email
            })
            
        # Update password
        print(f"[Password Reset Debug] Before update - User password hash: {user.password[:20]}...")
        user.set_password(new_password)  # Use set_password instead of make_password
        user.save()
        print(f"[Password Reset Debug] After update - User password hash: {user.password[:20]}...")
        print(f"[Password Reset Debug] Password successfully reset for user {user.username}")
        
        # Clear session
        if 'reset_email' in request.session:
            del request.session['reset_email']
        if 'otp_verified' in request.session:
            del request.session['otp_verified']
        print("[Password Reset Debug] Session cleared")
        
        messages.success(request, 'Your password has been reset successfully! You can now login with your new password.')
        return redirect('login_page')
    
    print(f"[Password Reset Debug] Rendering reset password form")
    return render(request, 'forgot_password.html', {
        'email_verified': True,
        'otp_verified': True,
        'email': email
    })

@login_required(login_url='login_page')
def orders_list(request):
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    
    # Pagination
    paginator = Paginator(orders, 10)  # Show 10 orders per page
    page = request.GET.get('page')
    orders = paginator.get_page(page)
    
    context = {
        'orders': orders
    }
    return render(request, 'orders_list.html', context)

@login_required(login_url='login_page')
def order_detail(request, order_id):
    try:
        order = get_object_or_404(Order, order_id=order_id, user=request.user)
        
        # Debug print
        print(f"DEBUG: Order found - ID: {order.order_id}, Status: {order.status}")
        print(f"DEBUG: Order items count: {order.items.count()}")
        
        context = {
            'order': order,
            'timeline': [
                {
                    'date': order.created_at,
                    'status': 'Order Placed',
                    'description': 'Your order has been placed successfully.'
                }
            ]
        }
        
        # Add status changes to timeline
        if order.status == 'CONFIRMED':
            context['timeline'].append({
                'date': order.updated_at,
                'status': 'Order Confirmed',
                'description': 'Your order has been confirmed and is being processed.'
            })
        elif order.status == 'SHIPPED':
            context['timeline'].extend([
                {
                    'date': order.updated_at,
                    'status': 'Order Confirmed',
                    'description': 'Your order has been confirmed and is being processed.'
                },
                {
                    'date': order.updated_at,
                    'status': 'Order Shipped',
                    'description': 'Your order has been shipped and is on its way.'
                }
            ])
        elif order.status == 'DELIVERED':
            context['timeline'].extend([
                {
                    'date': order.updated_at,
                    'status': 'Order Confirmed',
                    'description': 'Your order has been confirmed and is being processed.'
                },
                {
                    'date': order.updated_at,
                    'status': 'Order Shipped',
                    'description': 'Your order has been shipped and is on its way.'
                },
                {
                    'date': order.updated_at,
                    'status': 'Order Delivered',
                    'description': 'Your order has been delivered successfully.'
                }
            ])
        elif order.status == 'CANCELLED':
            context['timeline'].append({
                'date': order.cancelled_at or order.updated_at,
                'status': 'Order Cancelled',
                'description': f'Order cancelled. Reason: {order.cancel_reason or "No reason provided"}'
            })
        elif order.status == 'RETURNED':
            context['timeline'].extend([
                {
                    'date': order.updated_at,
                    'status': 'Order Delivered',
                    'description': 'Your order has been delivered successfully.'
                },
                {
                    'date': order.returned_at or order.updated_at,
                    'status': 'Order Returned',
                    'description': f'Order returned. Reason: {order.return_reason or "No reason provided"}'
                }
            ])
        
        # Add item-specific return events to the timeline
        if order.notes and 'Return requested for item' in order.notes:
            return_notes = order.notes.split('\n')
            for note in return_notes:
                if 'Return requested for item' in note:
                    context['timeline'].append({
                        'date': order.return_requested_at or order.updated_at,
                        'status': 'Item Return Requested',
                        'description': note
                    })
        
        return render(request, 'order_detail.html', context)
    except Order.DoesNotExist:
        messages.error(request, 'Order not found.')
        return redirect('user_profile:orders_list')

@login_required(login_url='login_page')
def cancel_order_page(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    # Check if order can be cancelled
    if order.status not in ['PENDING', 'CONFIRMED']:
        messages.error(request, 'This order cannot be cancelled')
        return redirect('user_profile:orders_list')
    
    context = {
        'order': order
    }
    return render(request, 'order_cancel.html', context)

@login_required(login_url='login_page')
def cancel_order(request, order_id):
    if request.method != 'POST':
        return redirect('user_profile:orders_list')
    
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    # Check if order can be cancelled
    if order.status not in ['PENDING', 'CONFIRMED']:
        messages.error(request, 'This order cannot be cancelled')
        return redirect('user_profile:orders_list')
    
    reason = request.POST.get('cancel_reason', '')
    if not reason:
        messages.error(request, 'Please provide a reason for cancellation')
        return redirect('user_profile:cancel_order_page', order_id=order_id)
    
    try:
        with transaction.atomic():
            # Update order status
            order.status = 'CANCELLED'
            order.cancelled_at = timezone.now()
            order.cancel_reason = reason
            order.save()
            
            # Restore stock for each item
            for item in order.items.all():
                product = item.product
                product.stock += item.quantity
                product.save()
            
            # Check if this user was referred and if a referral reward was given
            referral_history = ReferralHistory.objects.filter(referred_user=request.user, reward_given=True, reward_deducted=False).first()
            if referral_history:
                # Fixed reward amount of 100 rupees
                reward_amount = Decimal('100.00')
                
                # Deduct the reward from the referrer's wallet
                deduct_successful = deduct_referral_reward(
                    user=referral_history.referrer,
                    amount=reward_amount,
                    order_id=order.order_id,
                    reason='cancelled'
                )
                
                # Mark the referral reward as deducted
                if deduct_successful:
                    referral_history.reward_deducted = True
                    referral_history.save()
            
            # If the order was paid online, refund the amount to the user's wallet
            if order.payment_method != 'COD' and order.payment_status == 'PAID':
                # Get or create user's wallet
                wallet, created = Wallet.objects.get_or_create(user=request.user)
                
                # Add the refund amount to the wallet
                wallet.balance += order.total
                wallet.save()
                
                # Create a wallet transaction record
                WalletTransaction.objects.create(
                    wallet=wallet,
                    amount=order.total,
                    transaction_type='CREDIT',
                    status='COMPLETED',
                    description=f'Refund for cancelled order #{order.order_id}',
                    reference_id=order.order_id
                )
                
                # Update order payment status to REFUNDED
                order.payment_status = 'REFUNDED'
                order.save()
                
                # Add refund message to success message
                refund_message = f'₹{order.total} has been refunded to your wallet.'
            else:
                refund_message = ''
            
            # Send email notification
            subject = f'Order Cancellation Notification - Order #{order.order_id}'
            message = f'''
            Order #{order.order_id} has been cancelled.
            
            Customer: {request.user.get_full_name() or request.user.username}
            Order Date: {order.created_at.strftime('%Y-%m-%d %H:%M:%S')}
            Cancellation Date: {order.cancelled_at.strftime('%Y-%m-%d %H:%M:%S')}
            
            Reason for cancellation:
            {reason}
            
            Order Details:
            Total Amount: ₹{order.total}
            Items:
            {chr(10).join([f"- {item.quantity}x {item.product.title}" for item in order.items.all()])}
            
            {f"Refund Information: {refund_message}" if refund_message else ""}
            '''
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                ['booknestt@gmail.com'],
                fail_silently=False,
            )
            
            success_message = 'Order cancelled successfully'
            if refund_message:
                success_message += f' {refund_message}'
                
            messages.success(request, success_message)
            return redirect('user_profile:orders_list')
            
    except Exception as e:
        messages.error(request, f'An error occurred while cancelling the order: {str(e)}')
        return redirect('user_profile:cancel_order_page', order_id=order_id)

@login_required(login_url='login_page')
def return_order(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    # Check if order is eligible for return (delivered status)
    if order.status != 'DELIVERED':
        messages.error(request, "Only delivered orders can be returned.")
        return redirect('user_profile:orders_list')
    
    # Check if return request already exists
    if order.return_requested:
        messages.error(request, "A return request has already been submitted for this order.")
        return redirect('user_profile:orders_list')
    
    if request.method == 'POST':
        return_reason = request.POST.get('return_reason')
        additional_details = request.POST.get('additional_details')
        
        if not return_reason:
            messages.error(request, "Please select a reason for return.")
            return render(request, 'return_order.html', {'order': order})
        
        try:
            with transaction.atomic():
                # Update order with return request details
                order.return_requested = True
                order.return_reason = return_reason
                order.return_details = additional_details
                order.status = 'RETURN_REQUESTED'
                order.return_requested_at = timezone.now()
                order.save()
                
                # Get or create user's wallet
                wallet, created = Wallet.objects.get_or_create(user=request.user)
                
                # Create a pending wallet transaction for the return amount
                WalletTransaction.objects.create(
                    wallet=wallet,
                    amount=order.total,
                    transaction_type='CREDIT',
                    status='PENDING',
                    description=f'Refund for returned order #{order.order_id}',
                    reference_id=order.order_id
                )
                
                # Send email notification to admin
                subject = f'Return Request - Order #{order.order_id}'
                message = f'''
                Return request received for Order #{order.order_id}
                
                Customer: {request.user.get_full_name() or request.user.username}
                Order Date: {order.created_at.strftime('%Y-%m-%d %H:%M:%S')}
                Return Request Date: {order.return_requested_at.strftime('%Y-%m-%d %H:%M:%S')}
                
                Reason for return: {return_reason}
                Additional Details: {additional_details or 'No additional details provided'}
                
                Order Details:
                Total Amount: ₹{order.total}
                Items:
                {chr(10).join([f"- {item.quantity}x {item.product.title}" for item in order.items.all()])}
                '''
                
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    ['booknestt@gmail.com'],
                    fail_silently=False,
                )
            
            messages.success(request, "Return request submitted successfully. We will review your request shortly.")
            return redirect('user_profile:orders_list')
            
        except Exception as e:
            messages.error(request, f"An error occurred while processing your return request: {str(e)}")
            return render(request, 'return_order.html', {'order': order})
    
    # GET request - display the return form
    return render(request, 'return_order.html', {'order': order})

@login_required(login_url='login_page')
def return_item(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    # Check if order is eligible for return (delivered status)
    if order.status != 'DELIVERED':
        messages.error(request, "Only delivered orders can be returned.")
        return redirect('user_profile:order_detail', order_id=order_id)
    
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        return_reason = request.POST.get('reason')
        custom_reason = request.POST.get('custom_reason')
        return_method = request.POST.get('return_method')
        
        # Use custom reason if selected
        if return_reason == 'Other' and custom_reason:
            return_reason = custom_reason
        
        if not item_id or not return_reason:
            messages.error(request, "Please provide all required information.")
            return redirect('user_profile:order_detail', order_id=order_id)
        
        # Get the order item
        try:
            order_item = OrderItem.objects.get(id=item_id, order=order)
            
            # Check if this item is already marked for return
            if order_item.status in ['RETURN_REQUESTED', 'RETURNED', 'RETURN_REJECTED']:
                messages.error(request, "This item already has a return request.")
                return redirect('user_profile:order_detail', order_id=order_id)
            
            with transaction.atomic():
                # Update item status
                order_item.status = 'RETURN_REQUESTED'
                order_item.save()
                
                # Add return reason to order notes if not already there
                item_return_note = f"Return requested for item {order_item.product.title}: {return_reason} (Return method: {return_method})"
                if order.notes:
                    order.notes = order.notes + "\n" + item_return_note
                else:
                    order.notes = item_return_note
                
                # If this is the first item return request, update order status
                requested_items = order.items.filter(status='RETURN_REQUESTED').count()
                if requested_items == 1:  # This is the first item return
                    order.return_requested = True
                    order.return_requested_at = timezone.now()
                    
                order.save()
                
                # Get or create user's wallet
                wallet, created = Wallet.objects.get_or_create(user=request.user)
                
                # Calculate refund amount for this item
                refund_amount = order_item.total
                
                # Create a pending wallet transaction for the return amount
                WalletTransaction.objects.create(
                    wallet=wallet,
                    amount=refund_amount,
                    transaction_type='CREDIT',
                    status='PENDING',
                    description=f'Refund for returned item {order_item.product.title} (Order #{order.order_id})',
                    reference_id=f"{order.order_id}-{order_item.id}"
                )
                
                # Send email notification to admin
                subject = f'Item Return Request - Order #{order.order_id}'
                message = f'''
                Item return request received for Order #{order.order_id}
                
                Customer: {request.user.get_full_name() or request.user.username}
                Order Date: {order.created_at.strftime('%Y-%m-%d %H:%M:%S')}
                Return Request Date: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}
                
                Item: {order_item.product.title} (Quantity: {order_item.quantity})
                Reason for return: {return_reason}
                Return Method: {return_method}
                
                Refund Amount: ₹{refund_amount}
                '''
                
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    ['booknestt@gmail.com'],
                    fail_silently=False,
                )
                
            messages.success(request, f"Return request for '{order_item.product.title}' submitted successfully. We will review your request shortly.")
            return redirect('user_profile:order_detail', order_id=order_id)
        
        except OrderItem.DoesNotExist:
            messages.error(request, "The requested item could not be found.")
        except Exception as e:
            messages.error(request, f"An error occurred while processing your return request: {str(e)}")
    
    return redirect('user_profile:order_detail', order_id=order_id)

@login_required(login_url='login_page')
@csrf_protect
def toggle_wishlist(request, product_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})
    
    try:
        product = get_object_or_404(Product, id=product_id)
        wishlist_item = WishlistItem.objects.filter(user=request.user, product=product).first()
        
        if wishlist_item:
            # Remove from wishlist
            wishlist_item.delete()
            message = 'Product removed from wishlist'
        else:
            # Add to wishlist
            WishlistItem.objects.create(user=request.user, product=product)
            message = 'Product added to wishlist'
        
        return JsonResponse({'status': 'success', 'message': message})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required(login_url='login_page')
def wishlist_view(request):
    wishlist_items = WishlistItem.objects.filter(user=request.user).select_related('product')
    # Get current time for offer validation
    now = timezone.now()
    context = {
        'wishlist_items': wishlist_items,
        'now': now,  # Pass current time for offer validation
    }
    return render(request, 'wishlist.html', context)

@login_required(login_url='login_page')
def generate_invoice(request, order_id):
    try:
        order = get_object_or_404(Order, order_id=order_id, user=request.user)
        context = {
            'order': order,
            'timeline': [
                {
                    'date': order.created_at,
                    'status': 'Order Placed',
                    'description': 'Your order has been placed successfully.'
                }
            ]
        }
        
        # Add status changes to timeline
        if order.status == 'CONFIRMED':
            context['timeline'].append({
                'date': order.updated_at,
                'status': 'Order Confirmed',
                'description': 'Your order has been confirmed and is being processed.'
            })
        elif order.status == 'SHIPPED':
            context['timeline'].extend([
                {
                    'date': order.updated_at,
                    'status': 'Order Confirmed',
                    'description': 'Your order has been confirmed and is being processed.'
                },
                {
                    'date': order.updated_at,
                    'status': 'Order Shipped',
                    'description': 'Your order has been shipped and is on its way.'
                }
            ])
        elif order.status == 'DELIVERED':
            context['timeline'].extend([
                {
                    'date': order.updated_at,
                    'status': 'Order Confirmed',
                    'description': 'Your order has been confirmed and is being processed.'
                },
                {
                    'date': order.updated_at,
                    'status': 'Order Shipped',
                    'description': 'Your order has been shipped and is on its way.'
                },
                {
                    'date': order.updated_at,
                    'status': 'Order Delivered',
                    'description': 'Your order has been delivered successfully.'
                }
            ])
        elif order.status == 'CANCELLED':
            context['timeline'].append({
                'date': order.cancelled_at or order.updated_at,
                'status': 'Order Cancelled',
                'description': f'Order cancelled. Reason: {order.cancel_reason or "No reason provided"}'
            })
        elif order.status == 'RETURNED':
            context['timeline'].extend([
                {
                    'date': order.updated_at,
                    'status': 'Order Delivered',
                    'description': 'Your order has been delivered successfully.'
                },
                {
                    'date': order.returned_at or order.updated_at,
                    'status': 'Order Returned',
                    'description': f'Order returned. Reason: {order.return_reason or "No reason provided"}'
                }
            ])
        
        # Generate PDF
        template = get_template('invoice_template.html')
        html = template.render(context)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="invoice_{order.order_id}.pdf"'
        
        pisa.pisaDocument(BytesIO(html.encode("UTF-8")), response)
        return response
    except Exception as e:
        messages.error(request, f'An error occurred while generating the invoice: {str(e)}')
        return redirect('user_profile:orders_list')

@login_required(login_url='login_page')
def my_coupons(request):
    current_time = timezone.now()
    
    # Get user's personal coupons that are active and haven't been used
    user_coupons = Coupon.objects.filter(
        user=request.user, 
        is_active=True,
        expiry_date__gt=current_time
    ).order_by('-created_at')
    
    # Get global coupons that are active
    global_coupons = Coupon.objects.filter(
        user__isnull=True,
        is_active=True,
        expiry_date__gt=current_time
    ).order_by('-created_at')
    
    # Combine coupons
    all_coupons = list(user_coupons) + list(global_coupons)
    
    # Exclude coupons that have already been used by this user
    used_coupon_codes = set(CouponUsage.objects.filter(user=request.user).values_list('coupon__code', flat=True))
    
    # Filter out used coupons manually since we're using two separate querysets
    coupons = [coupon for coupon in all_coupons if coupon.code not in used_coupon_codes]
    
    # Get or generate user's referral code
    try:
        referral_code = ReferralCode.objects.get(user=request.user)
    except ReferralCode.DoesNotExist:
        # Generate a unique referral code
        import random
        import string
        
        def generate_code():
            chars = string.ascii_uppercase + string.digits
            return ''.join(random.choice(chars) for _ in range(8))
        
        code = generate_code()
        while ReferralCode.objects.filter(code__iexact=code).exists():
            code = generate_code()
        
        # Create the referral code
        referral_code = ReferralCode.objects.create(user=request.user, code=code)
    
    # Get active referral offer
    from admin_side.models import ReferralOffer
    
    referral_offer = ReferralOffer.objects.filter(
        is_active=True,
        start_date__lte=current_time,
        end_date__gte=current_time
    ).first()
    
    # Get referral history
    from admin_side.models import ReferralHistory
    referrals_made = ReferralHistory.objects.filter(referrer=request.user).order_by('-created_at')
    
    context = {
        'coupons': coupons,
        'referral_code': referral_code,
        'referral_offer': referral_offer,
        'referrals_made': referrals_made,
        'referral_url': request.build_absolute_uri(f'/signup/?ref={referral_code.code}')
    }
    
    return render(request, 'my_coupons.html', context)

@login_required(login_url='login_page')
def cancel_return_request(request, order_id):
    order = get_object_or_404(Order, order_id=order_id, user=request.user)
    
    # Check if order has a pending return request
    if order.status != 'RETURN_REQUESTED':
        messages.error(request, "This order does not have a pending return request.")
        return redirect('user_profile:orders_list')
    
    try:
        with transaction.atomic():
            # Update order status back to DELIVERED
            order.status = 'DELIVERED'
            order.return_requested = False
            order.save()
            
            # Delete any pending wallet transactions for this return
            wallet = Wallet.objects.filter(user=request.user).first()
            if wallet:
                WalletTransaction.objects.filter(
                    wallet=wallet,
                    reference_id=order.order_id,
                    transaction_type='CREDIT',
                    status='PENDING',
                    description__contains='Refund for returned order'
                ).delete()
            
            # Send email notification to admin
            subject = f'Return Request Cancelled - Order #{order.order_id}'
            message = f'''
            Return request for Order #{order.order_id} has been cancelled by the customer.
            
            Customer: {request.user.get_full_name() or request.user.username}
            Order Date: {order.created_at.strftime('%Y-%m-%d %H:%M:%S')}
            Return Request Cancellation Date: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}
            
            Order Details:
            Total Amount: ₹{order.total}
            Items:
            {chr(10).join([f"- {item.quantity}x {item.product.title}" for item in order.items.all()])}
            '''
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                ['booknestt@gmail.com'],
                fail_silently=False,
            )
        
        messages.success(request, "Return request cancelled successfully.")
        return redirect('user_profile:orders_list')
        
    except Exception as e:
        messages.error(request, f"An error occurred while cancelling your return request: {str(e)}")
        return redirect('user_profile:orders_list')

@login_required
def get_item_rejection_reason(request, item_id):
    """
    API endpoint to get the rejection reason for a specific item from the order notes
    """
    try:
        # Get the order item
        item = OrderItem.objects.select_related('order', 'product').get(id=item_id, order__user=request.user)
        
        if item.status != 'RETURN_REJECTED':
            return JsonResponse({'success': False, 'error': 'Item is not rejected'})
        
        # Get the order notes
        order_notes = item.order.notes
        
        if not order_notes:
            return JsonResponse({'success': True, 'rejection_reason': 'No reason provided'})
        
        # Find the rejection reason for this specific item
        # The pattern looks for a note that mentions this item's rejection
        product_title = item.product.title
        pattern = fr"Item '.*?{re.escape(product_title)}.*?' return rejected\. Reason: (.*?)(?:\n|$)"
        match = re.search(pattern, order_notes, re.IGNORECASE)
        
        if match:
            rejection_reason = match.group(1).strip()
            return JsonResponse({'success': True, 'rejection_reason': rejection_reason})
        
        # If no specific match, return the most recent rejection note
        notes_lines = order_notes.split('\n')
        for line in reversed(notes_lines):
            if 'return rejected' in line.lower() and 'reason' in line.lower():
                # Extract reason from line (assuming format: "... Reason: {reason}")
                reason_part = line.split('Reason:', 1)
                if len(reason_part) > 1:
                    rejection_reason = reason_part[1].strip()
                    return JsonResponse({'success': True, 'rejection_reason': rejection_reason})
        
        # As a fallback, return a generic message with the order notes
        return JsonResponse({
            'success': True, 
            'rejection_reason': 'Your return request was rejected. Please contact customer support for more details.'
        })
        
    except OrderItem.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Item not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})