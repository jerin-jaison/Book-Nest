from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.db.models import Q, Case, When, DecimalField, Avg, Count, Sum
from admin_side.models import Product, Category, ReferralCode, ReferralHistory, ProductOffer, CategoryOffer, Review
from django.core.paginator import Paginator
import random
from django.core.mail import send_mail
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from django.conf import settings
import logging
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email
from django.utils.dateparse import parse_datetime

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
    products = Product.objects.filter(status='active').prefetch_related('reviews')
    
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
    
    # Convert queryset to list to work with individual products
    products_list = list(products)
    
    # Get current time for offer validation
    now = timezone.now()
    
    # Calculate final prices including offers for each product
    for product in products_list:
        best_offer = product.get_best_offer()
        if best_offer and best_offer.is_valid():
            product._final_price = product.get_offer_price()
        elif product.discount_price:
            product._final_price = product.discount_price
        else:
            product._final_price = product.price
            
        # Calculate discount percentage for sorting by discount
        if best_offer and best_offer.is_valid():
            product.discount_percentage = best_offer.discount_percentage
        elif product.discount_price:
            product.discount_percentage = round(((product.price - product.discount_price) / product.price) * 100)
        else:
            product.discount_percentage = 0
    
    # Apply sorting with offer prices
    if sort_by == 'price_low':
        products_list.sort(key=lambda p: p._final_price)
    elif sort_by == 'price_high':
        products_list.sort(key=lambda p: p._final_price, reverse=True)
    elif sort_by == 'newest':
        products_list.sort(key=lambda p: p.created_at, reverse=True)
    elif sort_by == 'discount':
        products_list.sort(key=lambda p: p.discount_percentage, reverse=True)
    elif sort_by == 'title':
        products_list.sort(key=lambda p: p.title)
    
    # Calculate average ratings for each product
    product_ratings = {}
    product_review_counts = {}
    
    for product in products_list:
        reviews = product.reviews.all()
        avg_rating = reviews.aggregate(Avg('rating'))['rating__avg'] if reviews.exists() else 0
        avg_rating = round(avg_rating, 1) if avg_rating else 0
        product_ratings[product.id] = avg_rating
        product_review_counts[product.id] = reviews.count()
    
    # Pagination
    paginator = Paginator(products_list, 12)  # Show 12 products per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
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
        'total_results': len(products_list),
        'now': now,  # Pass current time for offer validation
        'product_ratings': product_ratings,  # Add ratings to context
        'product_review_counts': product_review_counts,  # Add review counts to context
    }
    
    return render(request, 'product_page.html', context)


@ensure_csrf_cookie
def product_detail_view(request, slug):
    # Get the product with prefetched images
    product = get_object_or_404(Product.objects.prefetch_related('additional_images', 'reviews'), slug=slug)
    
    # Remove welcome message to avoid duplicate notifications
    # if request.session.get('product_viewed_first_time') != slug:
    #     request.session['product_viewed_first_time'] = slug
    #     messages.info(request, f"Welcome to {product.title}! You can add this book to your cart or wishlist.")
    
    # Get related products (same category)
    related_products = Product.objects.filter(
        category=product.category,
        status='active'
    ).exclude(id=product.id)[:4]  # Get 4 related products
    
    # Get all product images including cover image
    product_images = [{'url': product.cover_image.url, 'is_cover': True}]
    for img in product.additional_images.all():
        product_images.append({'url': img.image.url, 'is_cover': False})
    
    # Get actual reviews for the product
    reviews = product.reviews.all().select_related('user')
    
    # Calculate average rating
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg'] if reviews.exists() else 0
    average_rating = round(average_rating, 1) if average_rating else 0
    
    # Check if user can leave a review (has purchased the product)
    can_review = False
    has_reviewed = False
    from cart_section.models import OrderItem, Order
    
    if request.user.is_authenticated:
        # Check if the user has already reviewed this product
        has_reviewed = Review.objects.filter(user=request.user, product=product).exists()
        
        # Check if the user has purchased this product and order is delivered
        has_purchased = OrderItem.objects.filter(
            order__user=request.user,
            product=product,
            order__status__in=['DELIVERED', 'COMPLETED']
        ).exists()
        
        can_review = has_purchased and not has_reviewed
    
    # Check if product is in user's wishlist
    is_in_wishlist = False
    if request.user.is_authenticated:
        # Check in user_authentication.Wishlist
        auth_wishlist = product.user_authentication_wishlist.filter(user=request.user).exists()
        
        # Check in user_profile.WishlistItem
        from user_profile.models import WishlistItem
        profile_wishlist = WishlistItem.objects.filter(user=request.user, product=product).exists()
        
        is_in_wishlist = auth_wishlist or profile_wishlist
        
        # Remove notification for wishlist status
        # if is_in_wishlist:
        #     messages.success(request, "This product is in your wishlist. You can purchase it now!")
    
    # Get current time for offer validation
    now = timezone.now()
    
    # Debug information for offers
    best_offer = product.get_best_offer()
    offer_info = None
    if best_offer:
        offer_info = {
            'id': best_offer.id,
            'title': best_offer.title,
            'discount': best_offer.discount_percentage,
            'is_valid': best_offer.is_valid(),
            'start_date': best_offer.start_date,
            'end_date': best_offer.end_date,
            'now': now,
            'is_active': best_offer.is_active,
            'type': 'Product Offer' if hasattr(best_offer, 'product') else 'Category Offer'
        }
        
        # Remove offer notification 
        # if best_offer.is_valid():
        #     messages.info(request, f"Special offer: {best_offer.discount_percentage}% discount on this product!")
    
    context = {
        'product': product,
        'product_images': product_images,
        'related_products': related_products,
        'reviews': reviews,
        'average_rating': average_rating,
        'rating_count': reviews.count(),
        'is_in_wishlist': is_in_wishlist,
        'now': now,  # Pass current time for offer validation
        'offer_info': offer_info,  # Debug information
        'can_review': can_review,
        'has_reviewed': has_reviewed,
    }
    
    return render(request, 'product_detail.html', context)


def signout_view(request):
    # Invalidate session on the server side
    request.session.flush()
    
    # Log the user out
    logout(request)
    
    # Redirect to login page with a response that has proper cache-control headers
    response = redirect('login_page')
    
    # Add cache control headers to ensure browsers don't use cached versions of pages
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    
    return response

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
        
        return HttpResponse(html_response)
    else:
        return JsonResponse({
            'status': 'error', 
            'message': 'No OTP found in session. Please generate an OTP first by signing up or requesting a password reset.'
        })
    
def custom_404_view(request, exception):
    return render(request, '404_page.html', status=404)

# Debug view for offers (only available to superusers)
@login_required
def debug_offers(request, product_id=None):
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('home_page')
    
    from admin_side.models import Product, ProductOffer, CategoryOffer
    from django.utils import timezone
    
    now = timezone.now()
    context = {
        'now': now,
        'products': [],
        'product_offers': [],
        'category_offers': []
    }
    
    if product_id:
        # Get specific product
        try:
            product = Product.objects.get(id=product_id)
            
            # Get all product offers for this product
            product_offers = ProductOffer.objects.filter(product=product).order_by('-created_at')
            
            # Get all category offers for this product's category
            category_offers = []
            if product.category:
                category_offers = CategoryOffer.objects.filter(category=product.category).order_by('-created_at')
            
            # Get the best offer
            best_offer = product.get_best_offer()
            
            context.update({
                'product': product,
                'product_offers': product_offers,
                'category_offers': category_offers,
                'best_offer': best_offer,
                'offer_price': product.get_offer_price() if best_offer else None
            })
        except Product.DoesNotExist:
            messages.error(request, f'Product with ID {product_id} not found.')
    else:
        # Get all products with active offers
        products_with_offers = Product.objects.filter(
            offers__is_active=True,
            offers__start_date__lte=now,
            offers__end_date__gte=now
        ).distinct()
        
        # Get all categories with active offers
        from admin_side.models import Category
        categories_with_offers = Category.objects.filter(
            offers__is_active=True,
            offers__start_date__lte=now,
            offers__end_date__gte=now
        ).distinct()
        
        # Get products in those categories
        products_with_category_offers = Product.objects.filter(
            category__in=categories_with_offers
        ).distinct()
        
        # Combine the lists
        all_products_with_offers = list(products_with_offers) + list(products_with_category_offers)
        # Remove duplicates
        all_products_with_offers = list(set(all_products_with_offers))
        
        context['products'] = all_products_with_offers
        context['product_offers'] = ProductOffer.objects.filter(is_active=True).order_by('-created_at')
        context['category_offers'] = CategoryOffer.objects.filter(is_active=True).order_by('-created_at')
    
    return render(request, 'debug_offers.html', context)

def contact_view(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # Check if the request is AJAX
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        try:
            # Send email to admin
            subject = f'Contact Form: {subject}'
            message = f'''
From: {name} <{email}>

Message:
{message}
            '''
            
            send_mail(
                subject,
                message,
                email,  # From email
                [settings.EMAIL_HOST_USER],  # To email (admin)
                fail_silently=False,
            )
            
            if is_ajax:
                return JsonResponse({'status': 'success', 'message': 'Your message has been sent successfully!'})
            messages.success(request, 'Your message has been sent successfully!')
            
        except Exception as e:
            logger.error(f"Error sending contact form email: {str(e)}")
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Failed to send message. Please try again.'})
            messages.error(request, 'Failed to send message. Please try again.')
        
        return redirect('contact')
    
    return render(request, 'contact.html')

@login_required
def add_review(request, product_id):
    """View to handle adding product reviews"""
    if request.method != 'POST':
        return redirect('product_list')
    
    # Get the product
    product = get_object_or_404(Product, id=product_id)
    
    # Check if user has purchased this product
    from cart_section.models import OrderItem
    has_purchased = OrderItem.objects.filter(
        order__user=request.user,
        product=product,
        order__status__in=['DELIVERED', 'COMPLETED']
    ).exists()
    
    # Check if user has already reviewed this product
    from admin_side.models import Review
    has_reviewed = Review.objects.filter(user=request.user, product=product).exists()
    
    if not has_purchased:
        messages.error(request, "You can only review products you have purchased.")
        return redirect('product_detail', slug=product.slug)
    
    if has_reviewed:
        messages.error(request, "You have already reviewed this product.")
        return redirect('product_detail', slug=product.slug)
    
    # Get review data
    rating = request.POST.get('rating')
    comment = request.POST.get('comment')
    
    if not rating or not comment:
        messages.error(request, "Please provide both rating and comment.")
        return redirect('product_detail', slug=product.slug)
    
    try:
        # Create the review
        review = Review(
            product=product,
            user=request.user,
            rating=int(rating),
            comment=comment,
            verified_purchase=True  # Since we've verified the purchase
        )
        review.save()
        messages.success(request, f"Thank you for your {rating}-star review! Your feedback helps other customers make informed decisions.")
    except Exception as e:
        messages.error(request, f"Error submitting review: {str(e)}")
    
    return redirect('product_detail', slug=product.slug)

@login_required
def edit_review(request, review_id):
    """View to handle editing a review"""
    # Get the review and check ownership
    from admin_side.models import Review
    review = get_object_or_404(Review, id=review_id)
    
    if review.user != request.user:
        messages.error(request, "You can only edit your own reviews.")
        return redirect('product_detail', slug=review.product.slug)
    
    if request.method == 'POST':
        # Get updated data
        rating = request.POST.get('rating')
        comment = request.POST.get('comment')
        
        if not rating or not comment:
            messages.error(request, "Please provide both rating and comment.")
            return redirect('product_detail', slug=review.product.slug)
        
        try:
            # Update the review
            old_rating = review.rating
            review.rating = int(rating)
            review.comment = comment
            review.updated_at = timezone.now()  # Update timestamp
            review.save()
            
            # Customize the message based on rating change
            if old_rating < int(rating):
                messages.success(request, f"Your review has been updated! We're glad to see you've given this product a higher rating.")
            elif old_rating > int(rating):
                messages.success(request, f"Your review has been updated. We appreciate your honest feedback.")
            else:
                messages.success(request, f"Your review has been updated successfully!")
        except Exception as e:
            messages.error(request, f"Error updating review: {str(e)}")
    
    return redirect('product_detail', slug=review.product.slug)

@login_required
def delete_review(request, review_id):
    """View to handle deleting a review"""
    # Get the review and check ownership
    from admin_side.models import Review
    review = get_object_or_404(Review, id=review_id)
    product_slug = review.product.slug
    product_title = review.product.title
    
    if review.user != request.user:
        messages.error(request, "You can only delete your own reviews.")
        return redirect('product_detail', slug=product_slug)
    
    if request.method == 'POST':
        try:
            # Delete the review
            review.delete()
            messages.success(request, f"Your review for '{product_title}' has been deleted. You can add a new review anytime.")
        except Exception as e:
            messages.error(request, f"Error deleting review: {str(e)}")
    
    return redirect('product_detail', slug=product_slug)