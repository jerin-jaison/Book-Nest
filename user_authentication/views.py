from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.db.models import Q, Case, When, DecimalField
from admin_side.models import Product, Category, ReferralCode, ReferralHistory
from django.core.paginator import Paginator
import random
from django.core.mail import send_mail
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.utils import timezone
from django.http import JsonResponse
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Utility function to print current OTP
def print_current_otp(request):
    otp = request.session.get('reset_otp')
    email = request.session.get('reset_email')
    print("\n" + "=" * 50)
    print(f"CURRENT SESSION OTP INFO:")
    print(f"- Email: {email}")
    print(f"- OTP: {otp}")
    print("=" * 50 + "\n")
    return otp

# Create your views here.


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home_page')

    # Check for referral code in URL
    referral_code_from_url = request.GET.get('ref')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        first_name = request.POST.get('firstName')
        last_name = request.POST.get('lastName')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirmPassword = request.POST.get('confirmPassword')
        referral_code = request.POST.get('referralCode')

        # Check if the request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        # Validate user input before creating user
        if User.objects.filter(username=username).exists():
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Username already exists'})
            messages.error(request, 'Username exists')
            return redirect('signup_page')
        
        if User.objects.filter(email=email).exists():
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Email already exists'})
            messages.error(request, 'Email already exists')
            return redirect('signup_page')
        
        if password != confirmPassword:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Passwords do not match'})
            messages.error(request, 'Please enter the same password')
            return redirect('signup_page')
        
        # Validate referral code if provided (before creating user)
        referrer = None
        if referral_code:
            try:
                referrer_code = ReferralCode.objects.get(code=referral_code)
                referrer = referrer_code.user
            except ReferralCode.DoesNotExist:
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': 'Invalid referral code'})
                messages.error(request, 'Invalid referral code')
                return redirect('signup_page')
            except Exception as e:
                logger.error(f"Error processing referral")
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': 'Error processing referral code'})
                messages.error(request, 'Error processing referral code')
                return redirect('signup_page')
        
        # Generate OTP
        otp = str(random.randint(100000, 999999))
        print(f" OTP {username}: {otp}")
        

        
        # Store in session
        request.session['reset_otp'] = otp
        request.session['reset_email'] = email
        
        # Store user details in session instead of creating user right away
        request.session['pending_user'] = {
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'password': password,
            'referral_code': referral_code if referral_code else None
        }
        
        # Send email with error handling
        subject = 'Your OTP for SignUp'
        message = f'''
Hello {first_name},

Thank you for signing up with BookNest! Your verification code is:

{otp}

This code will expire in 5 minutes. If you did not request this code, please ignore this email.

Best regards,
BookNest Team
'''
        try:
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [email],
                fail_silently=False
            )
            logger.info(f"OTP email sent successfully")
            
            if is_ajax:
                return JsonResponse({'status': 'success', 'message': 'Signup information validated! OTP sent to your email.'})
            
            messages.success(request, 'Signup information validated! OTP sent to your email.')
            return redirect('otp_page_login')
            
        except Exception as e:
            logger.error(f"Error sending email")
            
            if is_ajax:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Unable to send verification email. Please try again later.'
                })
            
            messages.error(request, 'Unable to send verification email. Please try again later.')
            return redirect('signup_page')

    return render(request, 'signup_page.html')


def otpLogin_view(request):
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        
        # Check if the request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Get stored OTP and pending user details from session
        stored_otp = request.session.get('reset_otp')
        pending_user = request.session.get('pending_user')
        
        # Check if OTP and user details exist in session
        if not stored_otp or not pending_user:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Session expired. Please sign up again.'})
            messages.error(request, 'Session expired. Please sign up again.')
            return redirect('signup_page')
        
        # Verify OTP
        if entered_otp and entered_otp == stored_otp:
            try:
                # Create user now that OTP is verified
                user = User.objects.create_user(
                    username=pending_user['username'],
                    first_name=pending_user['first_name'],
                    last_name=pending_user['last_name'],
                    email=pending_user['email'],
                    password=pending_user['password']
                )
                user.save()
                
                # Process referral if it exists
                if pending_user['referral_code']:
                    try:
                        referrer_code = ReferralCode.objects.get(code=pending_user['referral_code'])
                        ReferralHistory.objects.create(
                            referrer=referrer_code.user,
                            referred_user=user,
                            referral_code=pending_user['referral_code']
                        )
                    except Exception as e:
                        logger.error(f"Error processing referral during user creation")
                
                # Clear sensitive data from session
                request.session.pop('reset_otp', None)
                request.session.pop('pending_user', None)
                request.session['otp_validated'] = True
                
                if is_ajax:
                    return JsonResponse({'status': 'success', 'message': 'Account created successfully!'})
                messages.success(request, 'Account created successfully!')
                return redirect('login_page')
                
            except Exception as e:
                logger.error(f"Error creating user after OTP verification")
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': 'Error creating account. Please try again.'})
                messages.error(request, 'Error creating account. Please try again.')
                return redirect('signup_page')
        else:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Invalid OTP. Please try again.'})
            messages.error(request, 'Invalid OTP. Please try again.')
            
    return render(request, 'otp_signup.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home_page')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Check if the request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # First get the user object without authentication
        user = User.objects.filter(username=username).first()
        
        # Check if user exists and is blocked
        if user and not user.is_active:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Sorry, you are blocked by the admin.'})
            messages.error(request, 'Sorry, you are blocked by the admin.')
            return render(request, 'login_page.html')
            
        # Try to authenticate if user isn't blocked
        user = authenticate(request, username=username, password=password)
        if user is None:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Invalid credentials.'})
            messages.error(request, 'Invalid credentials.')
            return render(request, 'login_page.html')
        
        login(request, user)
        if is_ajax:
            return JsonResponse({'status': 'success', 'message': 'Login successful!', 'redirect': '/'})
        messages.success(request, 'Login successful!')
        return redirect('home_page')

    return render(request, 'login_page.html')


# Google authentication
 
def google_login(request):
    if request.user.is_authenticated:
        return redirect('home_page')
    return redirect('social:begin', 'google-oauth2')


def forgetPassword_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        
        # Check if the request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if not User.objects.filter(email=email).exists():
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Email not recognized'})
            messages.error(request, 'Email not recognized')
            return redirect('forgetPassword_page')

        otp = str(random.randint(100000, 999999))
        logger.info(f"Password reset OTP for {email}: {otp}")
        
        # Store in session
        request.session['reset_otp'] = otp
        request.session['reset_email'] = email
        
        # Send email with error handling
        subject = 'Your OTP for Password Reset'
        message = f'''
Hello,

You have requested to reset your password. Your verification code is:

{otp}

This code will expire in 5 minutes. If you did not request this code, please ignore this email.

Best regards,
BookNest Team
'''
        try:
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER if not settings.DEBUG else 'booknestt@gmail.com',
                [email],
                fail_silently=settings.DEBUG
            )
            logger.info(f"Password reset OTP email sent successfully to {email}")
            
            
            if settings.DEBUG:
                print("\n" + "*" * 50)
                print(f"* PASSWORD RESET OTP for {email}: {otp}")
                print("*" * 50 + "\n")
            
            if is_ajax:
                if settings.DEBUG:
                    return JsonResponse({'status': 'success', 'message': f'Your password reset OTP is: {otp}'})
                else:
                    return JsonResponse({'status': 'success', 'message': 'OTP sent successfully'})
            
            # if settings.DEBUG:
            #     messages.info(request, f'Your password reset OTP is: {otp}')
            # else:
            #     messages.success(request, 'OTP sent successfully')
            return redirect('otp_page')
        except Exception as e:
            logger.error(f"Error sending password reset email: {str(e)}")
            if settings.DEBUG:
                print("\n" + "*" * 50)
                print(f"* PASSWORD RESET OTP for {email}: {otp}")
                print(f"* (Email sending failed: {str(e)})")
                print("*" * 50 + "\n")
                
                if is_ajax:
                    return JsonResponse({
                        'status': 'success',
                        # 'message': f'Your password reset OTP is: {otp}'
                    })
                messages.success(request, 'OTP generated successfully')
                # messages.info(request, f'Your OTP is: {otp}')
                return redirect('otp_page')
            else:
                if is_ajax:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Unable to send verification email. Please try again later.'
                    })
                messages.error(request, 'Unable to send verification email. Please try again later.')
                return redirect('forgetPassword_page')
        
    return render(request, 'forget_password.html')


def otpSignup_view(request):
    # Print current OTP at the beginning of the view
    if settings.DEBUG:
        stored_otp = print_current_otp(request)
        
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        
        # Check if the request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Get stored OTP from session
        stored_otp = request.session.get('reset_otp')
        
        # Debug information
        logger.info(f"OTP Verification - Entered: {entered_otp}, Stored: {stored_otp}")
        print("\n" + "-" * 50)
        print(f"OTP VERIFICATION ATTEMPT:")
        print(f"- Entered OTP: {entered_otp}")
        print(f"- Stored OTP: {stored_otp}")
        print("-" * 50 + "\n")
        
        # Check if OTP exists in session
        if not stored_otp:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'OTP session expired. Please request a new OTP.'})
            messages.error(request, 'OTP session expired. Please request a new OTP.')
            return redirect('forgetPassword_page')
        
        # Verify OTP
        if entered_otp and entered_otp == stored_otp:
            request.session['otp_validated'] = True
            if is_ajax:
                return JsonResponse({'status': 'success', 'message': 'OTP verification successful'})
            messages.success(request, 'OTP verification successful')
            return redirect('reEnterPassword_page')
        # else:
        #     if is_ajax:
        #         if settings.DEBUG:
        #             return JsonResponse({
        #                 'status': 'error', 
        #                 'message': f'Invalid OTP. You entered: {entered_otp}, Expected: {stored_otp}'
        #             })
        #         else:
        #             return JsonResponse({'status': 'error', 'message': 'Invalid OTP. Please try again.'})
            
        #     if settings.DEBUG:
        #         messages.error(request, f'Invalid OTP. You entered: {entered_otp}, Expected: {stored_otp}')
        #     else:
        #         messages.error(request, 'Invalid OTP. Please try again.')
            
    return render(request, 'otp_signup.html')


def reEnterPassword_view(request):
    # Check if email is in session
    if not request.session.get('reset_email'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error', 
                'message': 'Session expired. Please restart the password reset process.'
            })
        messages.error(request, 'Session expired. Please restart the password reset process.')
        return redirect('forgetPassword_page')

    # Check if OTP has been validated
    if not request.session.get('otp_validated'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error', 
                'message': 'OTP not verified. Please verify your OTP first.'
            })
        messages.error(request, 'OTP not verified. Please verify your OTP first.')
        return redirect('otp_page')
    
    if request.method == 'POST':
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
    
        # Check if the request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        # Validate password
        if not password or len(password) < 8:
            if is_ajax:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'Password must be at least 8 characters long.'
                })
            messages.error(request, 'Password must be at least 8 characters long.')
            return redirect('reEnterPassword_page')

        # Check if passwords match
        if password != confirm_password:
            if is_ajax:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'Passwords do not match. Please enter the same password in both fields.'
                })
            messages.error(request, 'Passwords do not match. Please enter the same password in both fields.')
            return redirect('reEnterPassword_page')
        
        try:
            # Get user and update password
            user = User.objects.get(email=request.session['reset_email'])
            user.set_password(password)
            user.save()

            # Clear session data
            request.session.pop('reset_otp', None)
            request.session.pop('reset_email', None)
            request.session.pop('otp_validated', None)
            
            # Log the successful password reset
            logger.info(f"Password reset successful for user: {user.username} ({user.email})")
                
            if is_ajax:
                return JsonResponse({
                    'status': 'success', 
                    'message': 'Password reset successful! You can now login with your new password.',
                    'redirect': '/login/'
                })
            messages.success(request, 'Password reset successful! You can now login with your new password.')
            return redirect('login_page')
        
        except User.DoesNotExist:
            logger.error(f"Password reset failed: User with email {request.session.get('reset_email')} not found")
            if is_ajax:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'User not found. Please restart the password reset process.'
                })
            messages.error(request, 'User not found. Please restart the password reset process.')
            return redirect('forgetPassword_page')
        
        except Exception as e:
            logger.error(f"Password reset error: {str(e)}")
            if is_ajax:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'An error occurred while resetting your password. Please try again.'
                })
            messages.error(request, 'An error occurred while resetting your password. Please try again.')
            return redirect('reEnterPassword_page')
    
    return render(request, 're-enter_password.html')


#Resend OTP
def resend_otp(request):
    email = request.session.get('reset_email')
    
    if not email:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Please start the process again'})
        messages.error(request, 'Please start the process again')
        return redirect('forget_password')
    
    # Generate new OTP
    otp = str(random.randint(100000, 999999))
    logger.info(f"Resending OTP for {email}: {otp}")
    
    # Update session with new OTP
    request.session['reset_otp'] = otp
    
    # Send email with error handling
    subject = 'Your New OTP for Password Reset'
    message = f'''
Hello,

You have requested a new verification code. Your new code is:

{otp}

This code will expire in 5 minutes. If you did not request this code, please ignore this email.

Best regards,
BookNest Team
'''
    try:
        send_mail(
            subject,
            message,
            settings.EMAIL_HOST_USER if not settings.DEBUG else 'booknestt@gmail.com',
            [email],
            fail_silently=settings.DEBUG
        )
        logger.info(f"New OTP email sent successfully to {email}")
        
        # Always print OTP in development mode for debugging
        if settings.DEBUG:
            print("\n" + "*" * 50)
            print(f"* RESENT OTP for {email}: {otp}")
            print("*" * 50 + "\n")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            if settings.DEBUG:
                return JsonResponse({'status': 'success', 'message': f'Your new OTP is: {otp}'})
            else:
                return JsonResponse({'status': 'success', 'message': 'New OTP sent successfully'})
        
        if settings.DEBUG:
            messages.info(request, f'Your new OTP is: {otp}')
        else:
            messages.success(request, 'New OTP sent successfully')
        return redirect('otp_page')
    except Exception as e:
        logger.error(f"Error sending new OTP email: {str(e)}")
        if settings.DEBUG:
            print("\n" + "*" * 50)
            print(f"* RESENT OTP for {email}: {otp}")
            print(f"* (Email sending failed: {str(e)})")
            print("*" * 50 + "\n")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'success',
                    'message': f'Your new OTP is: {otp}'
                })
            messages.success(request, 'New OTP generated successfully')
            messages.info(request, f'Your new OTP is: {otp}')
            return redirect('otp_page')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'error',
                    'message': 'Unable to send new OTP. Please try again later.'
                })
            messages.error(request, 'Unable to send new OTP. Please try again later.')
            return redirect('forget_password')


def home_view(request):
    return render(request, 'index.html')


@ensure_csrf_cookie
def product_view(request):
    # Get all active products
    products = Product.objects.filter(status='active')
    
    # Get all categories for the navigation
    categories = Category.objects.all()
    
    # Get filter parameters
    search_query = request.GET.get('search', '').strip()
    category = request.GET.get('category')
    language = request.GET.get('language')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    sort_by = request.GET.get('sort_by', 'title')  # Default sort by title
    
    # Apply search filter
    if search_query:
        products = products.filter(
            Q(title__icontains=search_query) |
            Q(author__icontains=search_query) |
            Q(isbn__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Apply category filter
    if category:
        # Handle both predefined categories and database categories
        if category in ['self-help', 'comics', 'sci-fi', 'fiction', 'non-fiction', 'mystery', 'romance', 'biography']:
            products = products.filter(category__slug=category)
        else:
            try:
                category_id = int(category)
                products = products.filter(category_id=category_id)
            except (ValueError, TypeError):
                pass
    
    # Apply language filter
    if language:
        products = products.filter(language=language)
    
    # Apply price range filter
    if min_price:
        try:
            min_price = float(min_price)
            products = products.filter(Q(discount_price__gte=min_price) | 
                                    Q(Q(discount_price__isnull=True) & Q(price__gte=min_price)))
        except ValueError:
            pass
    
    if max_price:
        try:
            max_price = float(max_price)
            products = products.filter(Q(discount_price__lte=max_price) |
                                    Q(Q(discount_price__isnull=True) & Q(price__lte=max_price)))
        except ValueError:
            pass
    
    # Apply sorting
    if sort_by == 'price_low':
        products = products.annotate(
            final_price=Case(
                When(discount_price__isnull=False, then='discount_price'),
                default='price',
                output_field=DecimalField(),
            )
        ).order_by('final_price')
    elif sort_by == 'price_high':
        products = products.annotate(
            final_price=Case(
                When(discount_price__isnull=False, then='discount_price'),
                default='price',
                output_field=DecimalField(),
            )
        ).order_by('-final_price')
    elif sort_by == 'newest':
        products = products.order_by('-created_at')
    elif sort_by == 'title':
        products = products.order_by('title')
    
    # Get available languages for filter
    available_languages = dict(Product.LANGUAGE_CHOICES)
    
    # Predefined categories
    predefined_categories = [
        {'slug': 'self-help', 'name': 'Self-Help'},
        {'slug': 'comics', 'name': 'Comics'},
        {'slug': 'sci-fi', 'name': 'Science Fiction'},
        {'slug': 'fiction', 'name': 'Fiction'},
        {'slug': 'non-fiction', 'name': 'Non-Fiction'},
        {'slug': 'mystery', 'name': 'Mystery & Thriller'},
        {'slug': 'romance', 'name': 'Romance'},
        {'slug': 'biography', 'name': 'Biography'},
    ]
    
    # Pagination
    paginator = Paginator(products, 12)  # Show 12 products per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get current time for offer validation
    now = timezone.now()
    
    context = {
        'products': page_obj,
        'categories': categories,
        'predefined_categories': predefined_categories,
        'selected_category': category,
        'search_query': search_query,
        'selected_language': language,
        'min_price': min_price,
        'max_price': max_price,
        'sort_by': sort_by,
        'available_languages': available_languages,
        'total_results': products.count(),
        'now': now,  # Pass current time for offer validation
    }
    
    return render(request, 'product_page.html', context)


@ensure_csrf_cookie
def product_detail_view(request, slug):
    # Get the product with prefetched images
    product = get_object_or_404(Product.objects.prefetch_related('additional_images'), slug=slug)
    
    # Get related products (same category)
    related_products = Product.objects.filter(
        category=product.category,
        status='active'
    ).exclude(id=product.id)[:4]  # Get 4 related products
    
    # Get all product images including cover image
    product_images = [{'url': product.cover_image.url, 'is_cover': True}]
    for img in product.additional_images.all():
        product_images.append({'url': img.image.url, 'is_cover': False})
    
    # Demo ratings (we'll implement real ratings later)
    demo_ratings = [
        {'user': 'John', 'rating': 4.5, 'comment': 'This book changed my life! Clear and practical advice.', 'date': '2024-01-15'},
        {'user': 'Alice', 'rating': 5.0, 'comment': 'Excellent read, highly recommended!', 'date': '2024-02-01'},
    ]
    
    # Check if product is in user's wishlist (from either model)
    is_in_wishlist = False
    if request.user.is_authenticated:
        # Check in user_authentication.Wishlist
        auth_wishlist = product.user_authentication_wishlist.filter(user=request.user).exists()
        
        # Check in user_profile.WishlistItem
        from user_profile.models import WishlistItem
        profile_wishlist = WishlistItem.objects.filter(user=request.user, product=product).exists()
        
        is_in_wishlist = auth_wishlist or profile_wishlist
    
    # Get current time for offer validation
    now = timezone.now()
    
    context = {
        'product': product,
        'product_images': product_images,
        'related_products': related_products,
        'ratings': demo_ratings,
        'average_rating': 4.5,  # Demo average rating
        'rating_count': len(demo_ratings),
        'is_in_wishlist': is_in_wishlist,
        'now': now,  # Pass current time for offer validation
    }
    
    return render(request, 'product_detail.html', context)


def signout_view(request):
    request.session.flush()
    logout(request)
    return redirect('login_page')

# Debug view to print current OTP (only available in DEBUG mode)
def debug_otp(request):
    if not settings.DEBUG:
        return JsonResponse({'status': 'error', 'message': 'Debug mode is not enabled'})
    
    otp = print_current_otp(request)
    email = request.session.get('reset_email')
    
    if otp:
        # Create a simple HTML response for better readability
        html_response = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>OTP Debug Information</title>
            <style>
                body {{ font-family: Arial, sans-serif; padding: 20px; }}
                .debug-info {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; }}
                .otp-display {{ font-size: 24px; font-weight: bold; color: #007bff; margin: 20px 0; }}
                .email-display {{ color: #28a745; }}
            </style>
        </head>
        <body>
            <h1>OTP Debug Information</h1>
            <div class="debug-info">
                <p>Current session contains the following OTP information:</p>
                <p class="email-display">Email: <strong>{email}</strong></p>
                <p>OTP: <span class="otp-display">{otp}</span></p>
                <p>This information has also been printed to the console.</p>
            </div>
        </body>
        </html>
        """
        
        from django.http import HttpResponse
        return HttpResponse(html_response)
    else:
        return JsonResponse({
            'status': 'error', 
            'message': 'No OTP found in session. Please generate an OTP first by signing up or requesting a password reset.'
        })
    
def custom_404_view(request, exception):
    return render(request, '404_page.html', status=404)