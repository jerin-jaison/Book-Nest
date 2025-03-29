from django.shortcuts import render,redirect,get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Sum, F, ExpressionWrapper, DecimalField, Avg, Value
from django.db.models.functions import TruncMonth, TruncDay, TruncYear, TruncHour, Concat
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.core.paginator import Paginator
from .models import Product, ProductImage, Category, ProductOffer, CategoryOffer, ReferralOffer, ReferralCode, ReferralHistory, Coupon, Review
from cart_section.models import Order, OrderItem
from user_wallet.models import Wallet, WalletTransaction
import os
from datetime import datetime, timedelta
import csv
from django.db import transaction  # Fixed import for atomic transaction
from user_wallet.views import deduct_referral_reward
import re
from django.utils.text import slugify
from django.contrib.auth.decorators import user_passes_test
from user_wallet.views import deduct_referral_reward
from decimal import Decimal

def validate_image_file(image):
    # Check if file is an image
    if not image:
        return False, "No image file provided"
    
    # Get file extension
    file_ext = os.path.splitext(image.name)[1].lower()
    
    # List of valid image extensions
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif']
    
    # Check if extension is valid
    if file_ext not in valid_extensions:
        return False, "Invalid file type. Please upload a JPEG, PNG, or GIF file"
    
    # Check file size (max 5MB)
    if image.size > 5 * 1024 * 1024:  # 5MB in bytes
        return False, "File size too large. Maximum size is 5MB"
    
    return True, "Image is valid"

# Create your views here.

@never_cache
def admin_login_view(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('admin_side:admin_home')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username = username, password = password)

        if user is not None and user.is_superuser:
            login(request, user)
            return redirect('admin_side:admin_home')
        else:
            messages.error(request, 'Invalid admin credentials. Please try again.')
            return redirect('admin_side:admin_login')
        
    return render(request, 'admin_login.html')

@never_cache
@login_required(login_url='admin_side:admin_login')
def admin_home_view(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Get filter parameters
    time_range = request.GET.get('time_range', 'month')
    category_id = request.GET.get('category', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Set date range based on filters
    today = timezone.now().date()
    if start_date and end_date:
        # Custom date range
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        date_filter = Q(created_at__date__gte=start_date) & Q(created_at__date__lte=end_date)
    else:
        # Predefined ranges
        if time_range == 'today':
            date_filter = Q(created_at__date=today)
        elif time_range == 'week':
            week_ago = today - timedelta(days=7)
            date_filter = Q(created_at__date__gte=week_ago)
        elif time_range == 'month':
            month_ago = today - timedelta(days=30)
            date_filter = Q(created_at__date__gte=month_ago)
        elif time_range == 'year':
            year_ago = today - timedelta(days=365)
            date_filter = Q(created_at__date__gte=year_ago)
        else:  # all time
            date_filter = Q()
    
    # Apply category filter if specified
    if category_id:
        category_filter = Q(items__product__category_id=category_id)
    else:
        category_filter = Q()
    
    # Get orders with filters applied
    orders = Order.objects.filter(
        date_filter & category_filter
    ).annotate(
        items_count=Count('items')
    ).filter(
        items_count__gt=0
    ).select_related('user').prefetch_related('items__product')
    
    # Calculate order statistics
    total_orders = orders.count()
    pending_orders = orders.filter(status='PENDING').count()
    shipped_orders = orders.filter(status='SHIPPED').count()
    delivered_orders = orders.filter(status='DELIVERED').count()
    cancelled_orders = orders.filter(status='CANCELLED').count()
    
    # Calculate percentages for pie chart
    total_with_status = max(pending_orders + shipped_orders + delivered_orders + cancelled_orders, 1)
    pending_percentage = round((pending_orders / total_with_status) * 100)
    shipped_percentage = round((shipped_orders / total_with_status) * 100)
    delivered_percentage = round((delivered_orders / total_with_status) * 100)
    cancelled_percentage = round((cancelled_orders / total_with_status) * 100)
    
    # Calculate total sales
    total_sales = orders.filter(status__in=['DELIVERED', 'SHIPPED']).aggregate(Sum('total'))['total__sum'] or 0
    
    # Get recent orders
    recent_orders = orders.order_by('-created_at')[:5]
    
    # Get top selling products
    top_products = OrderItem.objects.filter(
        order__in=orders,
        order__status__in=['DELIVERED', 'SHIPPED']
    ).values(
        'product__id', 'product__title'
    ).annotate(
        total_sales=Sum(F('price') * F('quantity'))
    ).order_by('-total_sales')[:5]
    
    # Get top 10 products for modal
    top_ten_products = OrderItem.objects.filter(
        order__in=orders,
        order__status__in=['DELIVERED', 'SHIPPED']
    ).values(
        'product__id', 'product__title'
    ).annotate(
        total_sales=Sum(F('price') * F('quantity')),
        items_sold=Sum('quantity')
    ).order_by('-total_sales')[:10]
    
    # Get top 10 categories for modal
    top_categories = OrderItem.objects.filter(
        order__in=orders,
        order__status__in=['DELIVERED', 'SHIPPED']
    ).values(
        'product__category__id', 'product__category__name'
    ).annotate(
        total_sales=Sum(F('price') * F('quantity')),
        items_sold=Sum('quantity')
    ).order_by('-total_sales')[:10]
    
    # Format data for top products chart
    top_products_labels = [p['product__title'][:15] + '...' if len(p['product__title']) > 15 else p['product__title'] for p in top_products]
    top_products_data = [float(p['total_sales']) for p in top_products]
    
    # Get customer statistics
    total_customers = User.objects.filter(is_superuser=False).count()
    
    # Get product statistics
    products = Product.objects.all()
    total_products = products.count()
    low_stock_count = products.filter(stock__lte=10).count()
    stock_percentage = (total_products - low_stock_count) / total_products * 100 if total_products > 0 else 0
    
    # Get all categories for filter dropdown
    categories = Category.objects.filter(is_active=True)
    
    # Generate sales trend data (for mini chart)
    if time_range == 'today':
        # Hourly data for today
        sales_trend = Order.objects.filter(
            created_at__date=today,
            status__in=['DELIVERED', 'SHIPPED']
        ).annotate(
            hour=TruncHour('created_at')
        ).values('hour').annotate(
            total=Sum('total')
        ).order_by('hour')
        
        sales_trend_labels = [entry['hour'].strftime('%H:%M') for entry in sales_trend]
        sales_trend_data = [float(entry['total']) for entry in sales_trend]
        
        # Fill in missing hours
        if not sales_trend:
            sales_trend_labels = [f"{h:02d}:00" for h in range(24)]
            sales_trend_data = [0] * 24
    else:
        # Daily data for other time ranges
        if time_range == 'week':
            days = 7
        elif time_range == 'month':
            days = 30
        elif time_range == 'year':
            days = 365
        else:  # all time or custom range
            if start_date and end_date:
                days = (end_date - start_date).days + 1
            else:
                days = 30  # default to month view
        
        end_date = today
        start_date = end_date - timedelta(days=days-1)
        
        sales_trend = Order.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status__in=['DELIVERED', 'SHIPPED']
        ).annotate(
            day=TruncDay('created_at')
        ).values('day').annotate(
            total=Sum('total')
        ).order_by('day')
        
        # Create a dictionary with all dates in range
        date_range = {(start_date + timedelta(days=i)).strftime('%Y-%m-%d'): 0 for i in range(days)}
        
        # Fill in actual values
        for entry in sales_trend:
            date_key = entry['day'].strftime('%Y-%m-%d')
            date_range[date_key] = float(entry['total'])
        
        sales_trend_labels = list(date_range.keys())
        sales_trend_data = list(date_range.values())
    
    # Generate customer trend data (for mini chart)
    customer_trend_labels = sales_trend_labels
    customer_trend_data = [0] * len(sales_trend_labels)
    
    # Generate order trend data (for mini chart)
    order_trend_labels = sales_trend_labels
    order_trend_data = [0] * len(sales_trend_labels)
    
    # Generate sales chart data (for main chart)
    if time_range == 'month' or time_range == 'week':
        # Daily data for week/month
        sales_chart_labels = [f"{(today - timedelta(days=i)).strftime('%d %b')}" for i in range(days-1, -1, -1)]
        
        # Create a dictionary with all dates in range
        date_range = {(today - timedelta(days=i)).strftime('%Y-%m-%d'): 0 for i in range(days-1, -1, -1)}
        
        # Fill in actual values
        for entry in sales_trend:
            date_key = entry['day'].strftime('%Y-%m-%d')
            if date_key in date_range:
                date_range[date_key] = float(entry['total'])
        
        sales_chart_data = list(date_range.values())
    elif time_range == 'year':
        # Monthly data for year
        sales_chart = Order.objects.filter(
            created_at__date__gte=today - timedelta(days=365),
            status__in=['DELIVERED', 'SHIPPED']
        ).annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            total=Sum('total')
        ).order_by('month')
        
        # Create a dictionary with all months in range
        months = {}
        for i in range(12):
            month_date = today.replace(day=1) - timedelta(days=30*i)
            months[month_date.strftime('%Y-%m')] = 0
        
        # Fill in actual values
        for entry in sales_chart:
            month_key = entry['month'].strftime('%Y-%m')
            if month_key in months:
                months[month_key] = float(entry['total'])
        
        # Sort by date
        sorted_months = sorted(months.items(), key=lambda x: x[0])
        sales_chart_labels = [datetime.strptime(m[0], '%Y-%m').strftime('%b %Y') for m in sorted_months]
        sales_chart_data = [m[1] for m in sorted_months]
    else:
        # Use the same data as trend chart
        sales_chart_labels = sales_trend_labels
        sales_chart_data = sales_trend_data
    
    context = {
        'time_range': time_range,
        'selected_category': category_id,
        'categories': categories,
        'total_sales': total_sales,
        'total_orders': total_orders,
        'total_customers': total_customers,
        'total_products': total_products,
        'pending_orders': pending_orders,
        'shipped_orders': shipped_orders,
        'delivered_orders': delivered_orders,
        'cancelled_orders': cancelled_orders,
        'pending_percentage': pending_percentage,
        'shipped_percentage': shipped_percentage,
        'delivered_percentage': delivered_percentage,
        'cancelled_percentage': cancelled_percentage,
        'recent_orders': recent_orders,
        'top_products': top_products,
        'low_stock_count': low_stock_count,
        'stock_percentage': stock_percentage,
        'sales_trend_labels': sales_trend_labels,
        'sales_trend_data': sales_trend_data,
        'customer_trend_labels': customer_trend_labels,
        'customer_trend_data': customer_trend_data,
        'order_trend_labels': order_trend_labels,
        'order_trend_data': order_trend_data,
        'sales_chart_labels': sales_chart_labels,
        'sales_chart_data': sales_chart_data,
        'top_products_labels': top_products_labels,
        'top_products_data': top_products_data,
        'top_ten_products': top_ten_products,
        'top_categories': top_categories,
    }
    
    return render(request, 'admin_dashboard.html', context)

@never_cache
@login_required(login_url='admin_side:admin_login')
def admin_customers_view(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    users = User.objects.filter(is_superuser=False)
    users = users.order_by('-date_joined')
    #search query
    search_query = request.GET.get('search','')
    if search_query:
         users = users.filter(
                Q(username__icontains=search_query) |
                Q(email__icontains=search_query) 
                # Q(first_name__icontains=search_query) 
            )
    else:
        users = User.objects.all()

    return render(request, 'customer_management.html', {'users':users, 'search_query':search_query})

#Block User

@login_required(login_url='admin_side:admin_login')
def admin_blockUser_view(request, user_id):
    # Verify admin permission
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. You are not an admin.')
        return redirect('admin_side:admin_login')
    
    # Get user or return 404
    user = get_object_or_404(User, id=user_id)
    
    # Set user as inactive (blocked)
    user.is_active = False
    user.save()
    
    messages.success(request, f'User {user.username} has been blocked')
    return redirect('admin_side:customer_management')

#Unblock User

@login_required(login_url='admin_side:admin_login')

def admin_unblockUser_view(request, user_id):
    # Verify admin permission
    if not request.user.is_superuser:
        messages.error(request, 'Access denied. You are not an admin.')
        return redirect('admin_side:admin_login')
    
    # Get user or return 404
    user = get_object_or_404(User, id=user_id)
    
    # Set user as inactive (blocked)
    user.is_active = True
    user.save()
    
    messages.success(request, f'User {user.username} has been unblocked')
    return redirect('admin_side:customer_management')


#Product Edit
@login_required(login_url='admin_side:admin_login')
def addOrEditProduct_view(request, product_id=None):
    product = None if product_id is None else get_object_or_404(Product, id=product_id)
    categories = Category.objects.all()
    
    if request.method == 'POST':
        # Validate cover image if one was uploaded
        cover_image = request.FILES.get('cover_image')
        if cover_image:
            is_valid, message = validate_image_file(cover_image)
            if not is_valid:
                messages.error(request, message)
                return render(request, 'add_or_edit.html', {'product': product, 'categories': categories})
        
        # Validate additional images if any
        additional_images = request.FILES.getlist('additional_images')
        for image in additional_images:
            is_valid, message = validate_image_file(image)
            if not is_valid:
                messages.error(request, f"Additional image '{image.name}': {message}")
                return render(request, 'add_or_edit.html', {'product': product, 'categories': categories})
        
        if product is None:
            # Adding new product
            product = Product(
                title=request.POST['title'],
                author=request.POST['author'],
                isbn=request.POST['isbn'],
                description=request.POST['description'],
                price=request.POST['price'],
                discount_price=request.POST.get('discount_price') or None,
                stock=request.POST['stock'],
                category_id=request.POST['category'],
                publish_year=request.POST.get('publish_year') or None,
                language=request.POST.get('language'),
                page_count=request.POST.get('page_count') or None,
                status=request.POST['status']
            )
        else:
            # Updating existing product
            product.title = request.POST['title']
            product.author = request.POST['author']
            product.isbn = request.POST['isbn']
            product.description = request.POST['description']
            product.price = request.POST['price']
            product.discount_price = request.POST.get('discount_price') or None
            product.stock = request.POST['stock']
            product.category_id = request.POST['category']
            product.publish_year = request.POST.get('publish_year') or None
            product.language = request.POST.get('language')
            product.page_count = request.POST.get('page_count') or None
            product.status = request.POST['status']

        # Handle cover image
        if cover_image:
            product.cover_image = cover_image

        product.save()

        # Handle additional images
        if additional_images:
            for image in additional_images:
                ProductImage.objects.create(product=product, image=image)

        messages.success(request, 'Product updated successfully!' if product_id else 'Product added successfully!')
        return redirect('admin_side:product_list')

    return render(request, 'add_or_edit.html', {'product': product, 'categories': categories})

@login_required(login_url='admin_side:admin_login')
def delete_product(request, product_id):
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied, You are not admin'})
    
    if request.method == 'POST':
        try:
            product = get_object_or_404(Product, id=product_id)
            product_name = product.title
            product.delete()
            return JsonResponse({
                'success': True,
                'message': f'Product "{product_name}" deleted successfully!'
            })
        except Product.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Product not found'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error deleting product: {str(e)}'
            })
    
    return JsonResponse({
        'success': False,
        'message': 'Invalid request method'
    })

@login_required
def delete_product_image(request, image_id):
    if request.method == 'POST':
        image = get_object_or_404(ProductImage, id=image_id)
        image.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})

@never_cache
@login_required(login_url='admin_side:admin_login')
def product_list_view(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Get all products with their related data
    products = Product.objects.all().prefetch_related('additional_images').select_related('category')
    
    # Get all categories for the add product modal
    categories = Category.objects.all()
    
    # Handle search if present
    search_query = request.GET.get('search', '')
    if search_query:
        products = products.filter(
            Q(title__icontains=search_query) |
            Q(author__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    context = {
        'products': products,
        'categories': categories,
        'search_query': search_query
    }
    return render(request, 'product_list.html', context)

@never_cache
@login_required(login_url='admin_side:admin_login')
def edit_product_view(request, product_id):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    product = get_object_or_404(Product, id=product_id)
    categories = Category.objects.all()
    
    if request.method == 'POST':
        try:
            # Update product details
            product.title = request.POST.get('title')
            product.author = request.POST.get('author')
            product.isbn = request.POST.get('isbn')
            product.description = request.POST.get('description')
            product.price = float(request.POST.get('price'))
            product.stock = int(request.POST.get('stock'))
            
            # Update category - handle empty value
            category_id = request.POST.get('category')
            if category_id:
                try:
                    category_id = int(category_id)
                    product.category = get_object_or_404(Category, id=category_id)
                except (ValueError, Category.DoesNotExist):
                    messages.error(request, 'Invalid category selected')
                    return render(request, 'add_or_edit.html', {'product': product, 'categories': categories})
            else:
                product.category = None
            
            # Update discount price with proper validation
            discount_price = request.POST.get('discount_price')
            if discount_price and discount_price.strip():
                try:
                    discount_price = float(discount_price)
                    if discount_price >= product.price:
                        messages.error(request, 'Discount price must be less than regular price')
                        return render(request, 'add_or_edit.html', {'product': product, 'categories': categories})
                    product.discount_price = discount_price
                except ValueError:
                    messages.error(request, 'Invalid discount price format')
                    return render(request, 'add_or_edit.html', {'product': product, 'categories': categories})
            else:
                product.discount_price = None
            
            # Handle required fields with defaults
            product.language = request.POST.get('language', 'english')
            product.status = request.POST.get('status', 'active')
            
            # Handle optional fields
            publish_year = request.POST.get('publish_year')
            if publish_year:
                product.publish_year = int(publish_year)
            
            page_count = request.POST.get('page_count')
            if page_count:
                product.page_count = int(page_count)
            
            # Handle cover image
            if 'cover_image' in request.FILES:
                product.cover_image = request.FILES['cover_image']
            
            # Save the product first to ensure it exists
            product.save()
            
            # Handle additional images
            images = request.FILES.getlist('images')
            if images:
                # Create new product images
                for image in images:
                    ProductImage.objects.create(
                        product=product,
                        image=image
                    )
            
            messages.success(request, 'Product updated successfully!')
            return redirect('admin_side:product_list')
            
        except Exception as e:
            messages.error(request, f'Error updating product: {str(e)}')
    
    context = {
        'product': product,
        'categories': categories
    }
    return render(request, 'add_or_edit.html', context)

@never_cache
@login_required(login_url='admin_side:admin_login')
def add_product_view(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    categories = Category.objects.all()
    current_year = timezone.now().year
    form_data = None
    
    if request.method == 'POST':
        try:
            # Validate required fields
            required_fields = ['title', 'author', 'isbn', 'category', 'price', 'stock', 'description']
            for field in required_fields:
                if not request.POST.get(field):
                    raise ValueError(f'{field.title()} is required')

            # Validate numeric fields
            price = float(request.POST.get('price', 0))
            stock = int(request.POST.get('stock', 0))
            if price < 0:
                raise ValueError('Price cannot be negative')
            if stock < 0:
                raise ValueError('Stock cannot be negative')

            # Validate discount price
            discount_price = request.POST.get('discount_price')
            if discount_price:
                discount_price = float(discount_price)
                if discount_price >= price:
                    raise ValueError('Discount price must be less than regular price')

            # Validate ISBN
            isbn = request.POST.get('isbn')
            if not re.match(r'^(?=(?:\D*\d){10}(?:(?:\D*\d){3})?$)[\d-]+$', isbn):
                raise ValueError('Invalid ISBN format')

            # Validate publish year
            publish_year = int(request.POST.get('publish_year', 0))
            if publish_year < 1800 or publish_year > current_year:
                raise ValueError(f'Publish year must be between 1800 and {current_year}')

            # Validate page count
            page_count = int(request.POST.get('page_count', 0))
            if page_count < 1:
                raise ValueError('Page count must be greater than 0')

            # Create new product
            product = Product(
                title=request.POST.get('title'),
                author=request.POST.get('author'),
                isbn=isbn,
                description=request.POST.get('description'),
                price=price,
                stock=stock,
                language=request.POST.get('language'),
                publish_year=publish_year,
                page_count=page_count,
                status='active' if request.POST.get('is_active') == 'on' else 'inactive'
            )
            
            # Handle category
            category_id = request.POST.get('category')
            if category_id:
                try:
                    category_id = int(category_id)
                    product.category = get_object_or_404(Category, id=category_id)
                except (ValueError, Category.DoesNotExist):
                    raise ValueError('Invalid category selected')
            
            # Handle optional fields
            if discount_price:
                product.discount_price = discount_price
            
            # Validate cover image
            if 'cover_image' in request.FILES:
                cover_image = request.FILES['cover_image']
                is_valid, message = validate_image_file(cover_image)
                if not is_valid:
                    raise ValueError(f'Cover image: {message}')
                product.cover_image = cover_image
            else:
                raise ValueError('Cover image is required')
            
            product.save()
            
            # Handle additional images
            if request.FILES.getlist('additional_images'):
                for image in request.FILES.getlist('additional_images'):
                    is_valid, message = validate_image_file(image)
                    if not is_valid:
                        raise ValueError(f'Additional image: {message}')
                    ProductImage.objects.create(product=product, image=image)
            
            messages.success(request, 'Product added successfully!')
            return redirect('admin_side:product_list')
            
        except ValueError as e:
            messages.error(request, str(e))
            form_data = request.POST
        except Exception as e:
            messages.error(request, f'Error adding product: {str(e)}')
            form_data = request.POST
    
    context = {
        'categories': categories,
        'current_year': current_year,
        'form': {
            'title': {'value': form_data.get('title', '') if form_data else ''},
            'author': {'value': form_data.get('author', '') if form_data else ''},
            'isbn': {'value': form_data.get('isbn', '') if form_data else ''},
            'category': {'value': form_data.get('category', '') if form_data else ''},
            'price': {'value': form_data.get('price', '') if form_data else ''},
            'discount_price': {'value': form_data.get('discount_price', '') if form_data else ''},
            'stock': {'value': form_data.get('stock', '') if form_data else ''},
            'language': {'value': form_data.get('language', '') if form_data else ''},
            'publish_year': {'value': form_data.get('publish_year', '') if form_data else ''},
            'page_count': {'value': form_data.get('page_count', '') if form_data else ''},
            'description': {'value': form_data.get('description', '') if form_data else ''},
            'is_active': {'value': form_data.get('is_active', '') == 'on' if form_data else True},
        }
    }
    
    return render(request, 'product_list.html', context)

@login_required
def category_management(request):
    if not request.user.is_superuser:
        messages.error(request, "Access denied. You must be an admin to view this page.")
        return redirect('home_page')
    
    categories = Category.objects.all().order_by('name')
    context = {
        'categories': categories,
    }
    return render(request, 'category_management.html', context)

@login_required
def add_category(request):
    if not request.user.is_superuser:
        messages.error(request, "Access denied. You must be an admin to perform this action.")
        return redirect('home_page')
    
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            # Convert the input name to lowercase for case-insensitive comparison
            lowercase_name = name.lower()
            
            # Check if a category with this name (case-insensitive) already exists
            if Category.objects.filter(name__iexact=name).exists():
                messages.error(request, f'A category with the name "{name}" already exists (case-insensitive match). Please use a different name.')
                return redirect('admin_side:category_management')
            
            # Generate the initial slug
            base_slug = slugify(name)
            slug = base_slug
            counter = 1
            
            # Keep checking until we find a unique slug
            while Category.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            category = Category.objects.create(
                name=name,
                slug=slug,
                description=description,
                is_active=is_active
            )
            messages.success(request, f'Category "{category.name}" has been created successfully.')
        except Exception as e:
            messages.error(request, f'Error creating category: {str(e)}')
        
    return redirect('admin_side:category_management')

@login_required
def edit_category(request, category_id):
    if not request.user.is_superuser:
        messages.error(request, "Access denied. You must be an admin to perform this action.")
        return redirect('home_page')
    
    category = get_object_or_404(Category, id=category_id)
    
    if request.method == 'POST':
        try:
            new_name = request.POST.get('name')
            
            # Check if the name has changed
            if new_name.lower() != category.name.lower():
                # Check if a category with this name (case-insensitive) already exists
                if Category.objects.filter(name__iexact=new_name).exclude(id=category_id).exists():
                    messages.error(request, f'A category with the name "{new_name}" already exists (case-insensitive match). Please use a different name.')
                    return redirect('admin_side:category_management')
                
                # Only update slug if name has changed
                base_slug = slugify(new_name)
                slug = base_slug
                counter = 1
                
                # Keep checking until we find a unique slug, excluding current category
                while Category.objects.filter(slug=slug).exclude(id=category_id).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1
                
                category.slug = slug
            
            category.name = new_name
            category.description = request.POST.get('description')
            category.is_active = request.POST.get('is_active') == 'on'
            category.save()
            messages.success(request, f'Category "{category.name}" has been updated successfully.')
        except Exception as e:
            messages.error(request, f'Error updating category: {str(e)}')
    
    return redirect('admin_side:category_management')

@login_required
def delete_category(request, category_id):
    if not request.user.is_superuser:
        messages.error(request, "Access denied. You must be an admin to perform this action.")
        return redirect('home_page')
    
    category = get_object_or_404(Category, id=category_id)
    
    if request.method == 'POST':
        try:
            name = category.name
            category.delete()
            messages.success(request, f'Category "{name}" has been deleted successfully.')
        except Exception as e:
            messages.error(request, f'Error deleting category: {str(e)}')
    
    return redirect('admin_side:category_management')

@never_cache
def admin_logout_view(request):
    request.session.flush()
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('admin_side:admin_login')

@login_required(login_url='admin_side:admin_login')
def order_management(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Get filters from request
    status_filter = request.GET.get('status', '')
    date_filter = request.GET.get('date', '')
    search_query = request.GET.get('search', '')
    sort_by = request.GET.get('sort', '-created_at')
    
    # Base queryset with valid orders only (having at least one item)
    orders = Order.objects.annotate(
        items_count=Count('items')
    ).filter(
        items_count__gt=0
    ).select_related('user').prefetch_related('items__product')
    
    # Apply filters
    if status_filter:
        orders = orders.filter(status=status_filter.upper())
    
    if date_filter:
        today = timezone.now().date()
        if date_filter == 'today':
            orders = orders.filter(created_at__date=today)
        elif date_filter == 'week':
            week_ago = today - timedelta(days=7)
            orders = orders.filter(created_at__date__gte=week_ago)
        elif date_filter == 'month':
            month_ago = today - timedelta(days=30)
            orders = orders.filter(created_at__date__gte=month_ago)
    
    if search_query:
        orders = orders.filter(
            Q(order_id__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query)
        )
    
    # Apply sorting
    if sort_by == 'date-asc':
        orders = orders.order_by('created_at')
    elif sort_by == 'date-desc':
        orders = orders.order_by('-created_at')
    elif sort_by == 'amount-asc':
        orders = orders.order_by('total')
    elif sort_by == 'amount-desc':
        orders = orders.order_by('-total')
    
    # Get order statistics (excluding empty orders)
    total_orders = orders.count()
    pending_orders = orders.filter(status='PENDING').count()
    delivered_orders = orders.filter(status='DELIVERED').count()
    total_revenue = orders.filter(status__in=['DELIVERED', 'SHIPPED']).aggregate(Sum('total'))['total__sum'] or 0
    
    # Pagination
    paginator = Paginator(orders, 10)  # Show 10 orders per page
    page = request.GET.get('page')
    orders = paginator.get_page(page)
    
    context = {
        'orders': orders,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'delivered_orders': delivered_orders,
        'total_revenue': total_revenue,
        'status_filter': status_filter,
        'date_filter': date_filter,
        'search_query': search_query,
        'sort_by': sort_by,
    }
    
    return render(request, 'order_management.html', context)

@login_required(login_url='admin_side:admin_login')
def order_details(request, order_id):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    order = get_object_or_404(Order.objects.select_related('user', 'address')
                             .prefetch_related('items__product'), order_id=order_id)
    
    # Check if this is an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'order_details_partial.html', {'order': order})
    
    return render(request, 'order_details.html', {'order': order})

@login_required(login_url='admin_side:admin_login')
def update_order_status(request, order_id):
    if request.method == 'POST':
        try:
            status = request.POST.get('status')
            order = get_object_or_404(Order, order_id=order_id)
            
            # Update order status
            order.status = status
            order.save()
            
            # If order is cancelled, handle referral reward
            if status == 'CANCELLED':
                # Check if this user was referred and if a referral reward was given
                referral_history = ReferralHistory.objects.filter(referred_user=order.user, reward_given=True, reward_deducted=False).first()
                if referral_history:
                    # Instead of deducting from wallet, expire the coupon
                    expire_successful = expire_referral_reward_coupon(order)
                    
                    if expire_successful:
                        # Mark the referral reward as deducted to prevent further actions
                        referral_history.reward_deducted = True
                        referral_history.save()
            
            # Add a success message for non-AJAX requests
            messages.success(request, f'Order status updated to {status}')
            
            # Return JSON response for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Order status updated to {status}'
                })
            
            return redirect('admin_side:order_details', order_id=order_id)
        except Exception as e:
            # Log the error
            logger.error(f"Error updating order status: {str(e)}")
            
            # Add an error message for non-AJAX requests
            messages.error(request, f'Error updating order status: {str(e)}')
            
            # Return JSON response for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': f'Error updating order status: {str(e)}'
                })
            
            return redirect('admin_side:order_details', order_id=order_id)
    
    # Return JSON response for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': False,
            'message': 'Invalid request method'
        })
    
    return redirect('admin_side:order_management')

@login_required(login_url='admin_side:admin_login')
def get_return_details(request, order_id):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    order = get_object_or_404(Order, order_id=order_id)
    return JsonResponse({
        'reason': order.return_details,
        'requested_at': order.return_requested_at.strftime('%Y-%m-%d %H:%M:%S'),
        'total_amount': str(order.total)
    })

@login_required(login_url='admin_side:admin_login')
def process_return(request, order_id):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    action = request.POST.get('action')
    if action not in ['approve', 'reject']:
        return JsonResponse({'error': 'Invalid action'}, status=400)
    
    order = get_object_or_404(Order, order_id=order_id)
    
    if not order.return_requested:
        return JsonResponse({'error': 'No return request found for this order'}, status=400)
    
    try:
        with transaction.atomic():
            if action == 'approve':
                # Update order status
                order.status = 'RETURN_APPROVED'
                order.save()
                
                # Create or get user's wallet
                wallet, created = Wallet.objects.get_or_create(user=order.user)
                
                # Clean up any pending refund transactions
                cleaned_count = clean_pending_refund_transactions(order)
                
                # Check if a completed refund transaction already exists for this order
                existing_refund = WalletTransaction.objects.filter(
                    wallet=wallet,
                    reference_id=order.order_id,
                    transaction_type='CREDIT',
                    status='COMPLETED',
                    description__contains='Refund for returned order'
                ).exists()
                
                if not existing_refund:
                    # Add refund amount to wallet
                    wallet.balance += order.total
                    wallet.save()
                    
                    # Create wallet transaction record
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        amount=order.total,
                        transaction_type='CREDIT',
                        status='COMPLETED',
                        description=f'Refund for returned order #{order.order_id}',
                        reference_id=order.order_id
                    )
                    
                    messages.success(request, f'Return approved and ₹{order.total} refunded to user\'s wallet')
                else:
                    messages.info(request, f'Return approved. Refund was already processed.')
                
                # Check if this user was referred and if a referral reward was given
                referral_history = ReferralHistory.objects.filter(referred_user=order.user, reward_given=True, reward_deducted=False).first()
                if referral_history:
                    # Fixed reward amount of 100 rupees
                    reward_amount = Decimal('100.00')
                    
                    # Deduct the reward from the referrer's wallet
                    deduct_successful = deduct_referral_reward(
                        user=referral_history.referrer,
                        amount=reward_amount,
                        order_id=order.order_id,
                        reason='returned'
                    )
                    
                    # Mark the referral reward as deducted
                    if deduct_successful:
                        referral_history.reward_deducted = True
                        referral_history.save()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Return approved and amount credited to wallet'
                })
            else:  # reject
                order.status = 'RETURN_REJECTED'
                order.save()
                return JsonResponse({
                    'success': True,
                    'message': 'Return request rejected'
                })
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)

@login_required(login_url='admin_side:admin_login')
def approve_return(request, order_id):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                order = get_object_or_404(Order, order_id=order_id)
                
                # Check if return was requested
                if not order.return_requested:
                    messages.error(request, 'No return request found for this order')
                    return redirect('admin_side:order_details', order_id=order_id)
                
                # Update order status
                order.status = 'RETURNED'
                order.returned_at = timezone.now()
                
                # Update payment status to REFUNDED
                order.payment_status = 'REFUNDED'
                order.save()
                
                # Increment product stock for each returned item
                for item in order.items.all():
                    product = item.product
                    product.stock += item.quantity
                    product.save()
                
                # Process refund through wallet
                # Get or create user's wallet
                wallet, created = Wallet.objects.get_or_create(user=order.user)
                
                # Clean up any pending refund transactions
                cleaned_count = clean_pending_refund_transactions(order)
                
                # Check if a completed refund transaction already exists for this order
                existing_refund = WalletTransaction.objects.filter(
                    wallet=wallet,
                    reference_id=order.order_id,
                    transaction_type='CREDIT',
                    status='COMPLETED',
                    description__contains='Refund for returned order'
                ).exists()
                
                if not existing_refund:
                    # Add refund amount to wallet
                    wallet.balance += order.total
                    wallet.save()
                    
                    # Create wallet transaction record
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        amount=order.total,
                        transaction_type='CREDIT',
                        status='COMPLETED',
                        description=f'Refund for returned order #{order.order_id}',
                        reference_id=order.order_id
                    )
                    
                    messages.success(request, f'Return approved and ₹{order.total} refunded to user\'s wallet')
                else:
                    messages.info(request, f'Return approved. Refund was already processed.')
                
                # Handle referral reward
                # Check if this user was referred and if a referral reward was given
                referral_history = ReferralHistory.objects.filter(
                    referred_user=order.user, 
                    reward_given=True, 
                    reward_deducted=False
                ).first()
                
                if referral_history:
                    # Fixed reward amount of 100 rupees
                    reward_amount = Decimal('100.00')
                    
                    # Deduct the reward from the referrer's wallet
                    deduct_successful = deduct_referral_reward(
                        user=referral_history.referrer,
                        amount=reward_amount,
                        order_id=order.order_id,
                        reason='returned'
                    )
                    
                    # Mark the referral reward as deducted
                    if deduct_successful:
                        referral_history.reward_deducted = True
                        referral_history.save()
                
                return redirect('admin_side:order_details', order_id=order_id)
        except Exception as e:
            messages.error(request, f'Error approving return: {str(e)}')
            return redirect('admin_side:order_details', order_id=order_id)
    
    return redirect('admin_side:order_management')

@login_required(login_url='admin_side:admin_login')
def reject_return(request, order_id):
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    order = get_object_or_404(Order, order_id=order_id)
    
    try:
        # Save rejection notes if provided
        notes = request.POST.get('notes')
        if notes:
            order.notes = f"Return request rejected: {notes}"
        
        # Update order status to explicitly show return rejection
        order.status = 'RETURN_REJECTED'
        # Reset return request flag since it's now been handled
        order.return_requested = False
        order.return_requested_at = None
        
        # Make sure to save all changes
        order.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required(login_url='admin_side:admin_login')
def export_orders(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="orders_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Order ID', 'Date', 'Customer', 'Email', 'Items', 'Total', 'Status'])
    
    orders = Order.objects.all().select_related('user').prefetch_related('items__product')
    
    for order in orders:
        items_list = ', '.join([f"{item.quantity}x {item.product.title}" for item in order.items.all()])
        writer.writerow([
            order.order_id,
            order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            order.user.get_full_name() or order.user.username,
            order.user.email,
            items_list,
            order.total,
            order.status
        ])
    
    return response

@login_required(login_url='admin_side:admin_login')
def update_stock(request, product_id):
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    try:
        product = get_object_or_404(Product, id=product_id)
        new_stock = request.POST.get('stock')
        
        if new_stock is None:
            return JsonResponse({'success': False, 'message': 'Stock value is required'})
        
        try:
            new_stock = int(new_stock)
            if new_stock < 0:
                return JsonResponse({'success': False, 'message': 'Stock cannot be negative'})
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid stock value'})
        
        product.stock = new_stock
        product.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Stock updated successfully to {new_stock}',
            'new_stock': new_stock
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required(login_url='admin_side:admin_login')
def inventory_management(request):
    if not request.user.is_superuser:
        return redirect('home')
    
    # Get filter parameters
    search_query = request.GET.get('search', '')
    category_filter = request.GET.get('category', '')
    stock_filter = request.GET.get('stock', '')
    
    # Start with all products
    products = Product.objects.all()
    
    # Apply search filter
    if search_query:
        products = products.filter(
            Q(title__icontains=search_query) |
            Q(author__icontains=search_query) |
            Q(isbn__icontains=search_query)
        )
    
    # Apply category filter
    if category_filter:
        products = products.filter(category_id=category_filter)
    
    # Apply stock filter
    if stock_filter == 'low':
        products = products.filter(stock__gt=0, stock__lte=10)
    elif stock_filter == 'out':
        products = products.filter(stock=0)
    
    # Calculate statistics
    total_products = products.count()
    low_stock_products = products.filter(stock__gt=0, stock__lte=10).count()
    out_of_stock_products = products.filter(stock=0).count()
    total_stock_value = sum(product.price * product.stock for product in products)
    
    # Get all categories for the filter dropdown
    categories = Category.objects.all()
    
    context = {
        'products': products,
        'categories': categories,
        'total_products': total_products,
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
        'total_stock_value': total_stock_value,
        'search_query': search_query,
        'category_filter': category_filter,
        'stock_filter': stock_filter,
    }
    
    return render(request, 'inventory_management.html', context)

@login_required(login_url='admin_side:admin_login')
def low_stock_alerts(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Get products with low stock (10 or fewer items)
    low_stock_products = Product.objects.filter(stock__lte=10).select_related('category')
    
    context = {
        'products': low_stock_products,
        'threshold': 10
    }
    
    return render(request, 'low_stock_alerts.html', context)

@login_required(login_url='admin_side:admin_login')
def handle_return_request(request, order_id):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    order = get_object_or_404(Order, order_id=order_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        try:
            with transaction.atomic():
                if action == 'approve':
                    # Update order status
                    order.status = 'RETURNED'
                    order.returned_at = timezone.now()
                    
                    # Update payment status to REFUNDED
                    order.payment_status = 'REFUNDED'
                    order.save()
                    
                    # Increment product stock for each returned item
                    for item in order.items.all():
                        product = item.product
                        product.stock += item.quantity
                        product.save()
                    
                    # Process refund through wallet
                    # Get or create user's wallet
                    wallet, created = Wallet.objects.get_or_create(user=order.user)
                    
                    # Clean up any pending refund transactions
                    cleaned_count = clean_pending_refund_transactions(order)
                    
                    # Check if a completed refund transaction already exists for this order
                    existing_refund = WalletTransaction.objects.filter(
                        wallet=wallet,
                        reference_id=order.order_id,
                        transaction_type='CREDIT',
                        status='COMPLETED',
                        description__contains='Refund for returned order'
                    ).exists()
                    
                    if not existing_refund:
                        # Add refund amount to wallet
                        wallet.balance += order.total
                        wallet.save()
                        
                        # Create wallet transaction record
                        WalletTransaction.objects.create(
                            wallet=wallet,
                            amount=order.total,
                            transaction_type='CREDIT',
                            status='COMPLETED',
                            description=f'Refund for returned order #{order.order_id}',
                            reference_id=order.order_id
                        )
                        
                        refund_message = f'Stock updated and ₹{order.total} refunded to user\'s wallet.'
                    else:
                        refund_message = 'Refund was already processed.'
                    
                    # Check if this user was referred and if a referral reward was given
                    referral_history = ReferralHistory.objects.filter(
                        referred_user=order.user, 
                        reward_given=True, 
                        reward_deducted=False
                    ).first()
                    
                    if referral_history:
                        # Fixed reward amount of 100 rupees
                        reward_amount = Decimal('100.00')
                        
                        # Deduct the reward from the referrer's wallet
                        deduct_successful = deduct_referral_reward(
                            user=referral_history.referrer,
                            amount=reward_amount,
                            order_id=order.order_id,
                            reason='returned'
                        )
                        
                        # Mark the referral reward as deducted
                        if deduct_successful:
                            referral_history.reward_deducted = True
                            referral_history.save()
                    
                    messages.success(request, f'Return request approved for Order #{order.order_id}. {refund_message}')
                    
                elif action == 'reject':
                    # Update order status to return rejected
                    order.status = 'RETURN_REJECTED'
                    order.return_requested = False
                    order.return_requested_at = None
                    
                    # Add rejection notes
                    rejection_reason = request.POST.get('rejection_reason')
                    if rejection_reason:
                        order.notes = f"Return request rejected: {rejection_reason}"
                        
                    order.save()
                    
                    messages.success(request, f'Return request rejected for Order #{order.order_id}.')
        except Exception as e:
            messages.error(request, f'Error processing return request: {str(e)}')
    
    return redirect('admin_side:order_management')

# Function to check if user is admin
def is_admin(user):
    return user.is_superuser

# Create admin_required decorator
def admin_required(view_func):
    decorated_view_func = user_passes_test(is_admin)(view_func)
    return decorated_view_func

# Offer Management Views
@login_required
@user_passes_test(is_admin)
def offer_management(request):
    product_offers = ProductOffer.objects.all().order_by('-created_at')
    category_offers = CategoryOffer.objects.all().order_by('-created_at')
    referral_offers = ReferralOffer.objects.all().order_by('-created_at')
    
    context = {
        'product_offers': product_offers,
        'category_offers': category_offers,
        'referral_offers': referral_offers,
    }
    return render(request, 'offer_management.html', context)

# Product Offer Views
@login_required
@user_passes_test(is_admin)
def product_offer_list(request):
    offers = ProductOffer.objects.all().order_by('-created_at')
    context = {
        'offers': offers,
    }
    return render(request, 'product_offer_list.html', context)

@login_required
@user_passes_test(is_admin)
def add_product_offer(request):
    if request.method == 'POST':
        product_id = request.POST.get('product')
        title = request.POST.get('title')
        description = request.POST.get('description')
        discount_percentage = request.POST.get('discount_percentage')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            product = Product.objects.get(id=product_id)
            
            # Create the offer
            ProductOffer.objects.create(
                product=product,
                title=title,
                description=description,
                discount_percentage=discount_percentage,
                start_date=start_date,
                end_date=end_date,
                is_active=is_active
            )
            
            messages.success(request, 'Product offer added successfully!')
            return redirect('admin_side:product_offer_list')
        except Product.DoesNotExist:
            messages.error(request, 'Product not found!')
        except Exception as e:
            messages.error(request, f'Error adding product offer: {str(e)}')
    
    products = Product.objects.filter(status='active').order_by('title')
    context = {
        'products': products,
    }
    return render(request, 'add_product_offer.html', context)

@login_required
@user_passes_test(is_admin)
def edit_product_offer(request, offer_id):
    try:
        offer = ProductOffer.objects.get(id=offer_id)
    except ProductOffer.DoesNotExist:
        messages.error(request, 'Offer not found!')
        return redirect('admin_side:product_offer_list')
    
    if request.method == 'POST':
        product_id = request.POST.get('product')
        title = request.POST.get('title')
        description = request.POST.get('description')
        discount_percentage = request.POST.get('discount_percentage')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            product = Product.objects.get(id=product_id)
            
            # Update the offer
            offer.product = product
            offer.title = title
            offer.description = description
            offer.discount_percentage = discount_percentage
            offer.start_date = start_date
            offer.end_date = end_date
            offer.is_active = is_active
            offer.save()
            
            messages.success(request, 'Product offer updated successfully!')
            return redirect('admin_side:product_offer_list')
        except Product.DoesNotExist:
            messages.error(request, 'Product not found!')
        except Exception as e:
            messages.error(request, f'Error updating product offer: {str(e)}')
    
    products = Product.objects.filter(status='active').order_by('title')
    context = {
        'offer': offer,
        'products': products,
    }
    return render(request, 'edit_product_offer.html', context)

@login_required
@user_passes_test(is_admin)
def delete_product_offer(request, offer_id):
    try:
        offer = ProductOffer.objects.get(id=offer_id)
        offer.delete()
        messages.success(request, 'Product offer deleted successfully!')
    except ProductOffer.DoesNotExist:
        messages.error(request, 'Offer not found!')
    except Exception as e:
        messages.error(request, f'Error deleting product offer: {str(e)}')
    
    return redirect('admin_side:product_offer_list')

# Category Offer Views
@login_required
@user_passes_test(is_admin)
def category_offer_list(request):
    offers = CategoryOffer.objects.all().order_by('-created_at')
    context = {
        'offers': offers,
        'now': timezone.now(),
    }
    return render(request, 'category_offer_list.html', context)

@login_required
@user_passes_test(is_admin)
def add_category_offer(request):
    if request.method == 'POST':
        category_id = request.POST.get('category')
        title = request.POST.get('title')
        description = request.POST.get('description')
        discount_percentage = request.POST.get('discount_percentage')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            category = Category.objects.get(id=category_id)
            
            # Check if category name already exists case-insensitively
            category_name_lower = category.name.lower()
            existing_categories = Category.objects.filter(name__iexact=category.name).exclude(id=category.id)
            
            if existing_categories.exists():
                messages.error(request, f'A category with the name "{category.name}" already exists (case-insensitive match). Please choose a different name.')
                categories = Category.objects.filter(is_active=True).order_by('name')
                context = {
                    'categories': categories,
                    'now': timezone.now(),
                }
                return render(request, 'add_category_offer.html', context)
            
            # Create the offer
            CategoryOffer.objects.create(
                category=category,
                title=title,
                description=description,
                discount_percentage=discount_percentage,
                start_date=start_date,
                end_date=end_date,
                is_active=is_active
            )
            
            messages.success(request, 'Category offer added successfully!')
            return redirect('admin_side:category_offer_list')
        except Category.DoesNotExist:
            messages.error(request, 'Category not found!')
        except Exception as e:
            messages.error(request, f'Error adding category offer: {str(e)}')
    
    categories = Category.objects.filter(is_active=True).order_by('name')
    context = {
        'categories': categories,
        'now': timezone.now(),  # Add current time for default date values
    }
    return render(request, 'add_category_offer.html', context)

@login_required
@user_passes_test(is_admin)
def edit_category_offer(request, offer_id):
    try:
        offer = CategoryOffer.objects.get(id=offer_id)
    except CategoryOffer.DoesNotExist:
        messages.error(request, 'Offer not found!')
        return redirect('admin_side:category_offer_list')
    
    if request.method == 'POST':
        category_id = request.POST.get('category')
        title = request.POST.get('title')
        description = request.POST.get('description')
        discount_percentage = request.POST.get('discount_percentage')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            category = Category.objects.get(id=category_id)
            
            # Check if category name already exists case-insensitively
            category_name_lower = category.name.lower()
            existing_categories = Category.objects.filter(name__iexact=category.name).exclude(id=category.id)
            
            if existing_categories.exists():
                messages.error(request, f'A category with the name "{category.name}" already exists (case-insensitive match). Please choose a different name.')
                categories = Category.objects.filter(is_active=True).order_by('name')
                context = {
                    'offer': offer,
                    'categories': categories,
                    'now': timezone.now(),
                }
                return render(request, 'edit_category_offer.html', context)
            
            # Update the offer
            offer.category = category
            offer.title = title
            offer.description = description
            offer.discount_percentage = discount_percentage
            offer.start_date = start_date
            offer.end_date = end_date
            offer.is_active = is_active
            offer.save()
            
            messages.success(request, 'Category offer updated successfully!')
            return redirect('admin_side:category_offer_list')
        except Category.DoesNotExist:
            messages.error(request, 'Category not found!')
        except Exception as e:
            messages.error(request, f'Error updating category offer: {str(e)}')
    
    categories = Category.objects.filter(is_active=True).order_by('name')
    context = {
        'offer': offer,
        'categories': categories,
        'now': timezone.now(),  # Add current time for date comparison
    }
    return render(request, 'edit_category_offer.html', context)

@login_required
@user_passes_test(is_admin)
def delete_category_offer(request, offer_id):
    try:
        offer = CategoryOffer.objects.get(id=offer_id)
        offer.delete()
        messages.success(request, 'Category offer deleted successfully!')
    except CategoryOffer.DoesNotExist:
        messages.error(request, 'Offer not found!')
    except Exception as e:
        messages.error(request, f'Error deleting category offer: {str(e)}')
    
    return redirect('admin_side:category_offer_list')

# Referral Offer Views
@login_required
@user_passes_test(is_admin)
def referral_offer_list(request):
    offers = ReferralOffer.objects.all().order_by('-created_at')
    context = {
        'offers': offers,
        'now': timezone.now(),
    }
    return render(request, 'referral_offer_list.html', context)

@login_required
@user_passes_test(is_admin)
def add_referral_offer(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        discount_amount = request.POST.get('discount_amount')
        discount_percentage = request.POST.get('discount_percentage')
        min_purchase_amount = request.POST.get('min_purchase_amount')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            # Create the offer
            ReferralOffer.objects.create(
                title=title,
                description=description,
                discount_amount=discount_amount,
                discount_percentage=discount_percentage if discount_percentage else None,
                min_purchase_amount=min_purchase_amount,
                start_date=start_date,
                end_date=end_date,
                is_active=is_active
            )
            
            messages.success(request, 'Referral offer added successfully!')
            return redirect('admin_side:referral_offer_list')
        except Exception as e:
            messages.error(request, f'Error adding referral offer: {str(e)}')
    
    return render(request, 'add_referral_offer.html')

@login_required
@user_passes_test(is_admin)
def edit_referral_offer(request, offer_id):
    try:
        offer = ReferralOffer.objects.get(id=offer_id)
    except ReferralOffer.DoesNotExist:
        messages.error(request, 'Offer not found!')
        return redirect('admin_side:referral_offer_list')
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        discount_amount = request.POST.get('discount_amount')
        discount_percentage = request.POST.get('discount_percentage')
        min_purchase_amount = request.POST.get('min_purchase_amount')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            # Update the offer
            offer.title = title
            offer.description = description
            offer.discount_amount = discount_amount
            offer.discount_percentage = discount_percentage if discount_percentage else None
            offer.min_purchase_amount = min_purchase_amount
            offer.start_date = start_date
            offer.end_date = end_date
            offer.is_active = is_active
            offer.save()
            
            messages.success(request, 'Referral offer updated successfully!')
            return redirect('admin_side:referral_offer_list')
        except Exception as e:
            messages.error(request, f'Error updating referral offer: {str(e)}')
    
    context = {
        'offer': offer,
    }
    return render(request, 'edit_referral_offer.html', context)

@login_required
@user_passes_test(is_admin)
def delete_referral_offer(request, offer_id):
    try:
        offer = ReferralOffer.objects.get(id=offer_id)
        offer.delete()
        messages.success(request, 'Referral offer deleted successfully!')
    except ReferralOffer.DoesNotExist:
        messages.error(request, 'Offer not found!')
    except Exception as e:
        messages.error(request, f'Error deleting referral offer: {str(e)}')
    
    return redirect('admin_side:referral_offer_list')

@login_required
@user_passes_test(is_admin)
def referral_history(request):
    referrals = ReferralHistory.objects.all().order_by('-created_at')
    context = {
        'referrals': referrals,
    }
    return render(request, 'referral_history.html', context)

# Referral Code Management
@login_required
@user_passes_test(is_admin)
def generate_referral_code(request, user_id):
    try:
        user = User.objects.get(id=user_id)
        
        # Check if user already has a referral code
        try:
            referral_code = ReferralCode.objects.get(user=user)
            messages.info(request, f'User already has a referral code: {referral_code.code}')
        except ReferralCode.DoesNotExist:
            # Generate a unique referral code
            import random
            import string
            
            def generate_code():
                chars = string.ascii_uppercase + string.digits
                return ''.join(random.choice(chars) for _ in range(8))
            
            code = generate_code()
            # Check for case-insensitive duplicates
            while ReferralCode.objects.filter(code__iexact=code).exists():
                code = generate_code()
            
            # Create the referral code
            ReferralCode.objects.create(user=user, code=code)
            messages.success(request, f'Referral code {code} generated for {user.username}')
        
        return redirect('admin_side:user_details', user_id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'User not found!')
        return redirect('admin_side:users_list')
    except Exception as e:
        messages.error(request, f'Error generating referral code: {str(e)}')
        return redirect('admin_side:users_list')

@login_required(login_url='admin_side:admin_login')
def give_referral_reward(request, referral_id):
    """
    Give a referral reward to the referrer
    """
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    try:
        # Get the referral
        referral = ReferralHistory.objects.get(id=referral_id)
        
        # Check if reward already given
        if referral.reward_given:
            return JsonResponse({'success': False, 'message': 'Reward already given'})
        
        # Get active referral offer
        from django.utils import timezone
        now = timezone.now()
        
        referral_offer = ReferralOffer.objects.filter(
            is_active=True,
            start_date__lte=now,
            end_date__gte=now
        ).first()
        
        if not referral_offer:
            return JsonResponse({'success': False, 'message': 'No active referral offer found'})
        
        # Generate a unique coupon code
        import random
        import string
        
        def generate_unique_code(length=8):
            while True:
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
                # Use case-insensitive check for duplicates
                if not Coupon.objects.filter(code__iexact=code).exists():
                    return code
        
        coupon_code = generate_unique_code()
        
        # Set expiry date to 30 days from now
        expiry_date = timezone.now() + timedelta(days=30)
        
        # Create a coupon for the referrer
        coupon = Coupon.objects.create(
            user=referral.referrer,
            code=coupon_code,
            discount_amount=referral_offer.discount_amount,
            discount_percentage=referral_offer.discount_percentage,
            min_purchase_amount=referral_offer.min_purchase_amount,
            is_active=True,
            expiry_date=expiry_date,
            is_admin_generated=False  # This is a referral reward, not manually admin generated
        )
        
        # Mark referral as rewarded
        referral.reward_given = True
        referral.save()
        
        return JsonResponse({
            'success': True, 
            'message': f'Reward given successfully! Coupon code: {coupon_code}',
            'coupon_code': coupon_code
        })
        
    except ReferralHistory.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Referral not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

# Coupon Management Views
@login_required
@admin_required
def coupon_management(request):
    coupons = Coupon.objects.all().order_by('-created_at')
    users = User.objects.filter(is_superuser=False, is_active=True)
    
    context = {
        'coupons': coupons,
        'users': users,
        'today': timezone.now().date(),
    }
    return render(request, 'coupon_management.html', context)

@login_required
@admin_required
def create_coupon(request):
    if request.method == 'POST':
        try:
            code = request.POST.get('code')
            discount_type = request.POST.get('discount_type')
            discount_value = request.POST.get('discount_value')
            min_purchase_amount = request.POST.get('min_purchase_amount')
            expiry_date = request.POST.get('expiry_date')
            user_id = request.POST.get('user_id')
            
            # Validate inputs
            if not code or not discount_type or not discount_value or not min_purchase_amount or not expiry_date:
                return JsonResponse({'status': 'error', 'message': 'All fields are required'})
            
            # Convert code to lowercase for comparison
            lowercase_code = code.lower()
            
            # Check if coupon code already exists (case-insensitive)
            if Coupon.objects.filter(code__iexact=code).exists():
                return JsonResponse({'status': 'error', 'message': 'Coupon code already exists (case-insensitive match)'})
            
            # Convert values to appropriate types
            discount_value = float(discount_value)
            min_purchase_amount = float(min_purchase_amount)
            
            # Create coupon
            coupon = Coupon()
            coupon.code = code
            coupon.min_purchase_amount = min_purchase_amount
            coupon.expiry_date = expiry_date
            coupon.is_admin_generated = True  # Mark as admin generated
            
            # Set discount based on type
            if discount_type == 'percentage':
                if discount_value > 100:
                    return JsonResponse({'status': 'error', 'message': 'Percentage discount cannot exceed 100%'})
                coupon.discount_percentage = discount_value
                coupon.discount_amount = 0
            else:  # amount
                coupon.discount_amount = discount_value
                coupon.discount_percentage = 0
            
            # Assign to user if specified
            if user_id:
                try:
                    user = User.objects.get(id=user_id)
                    coupon.user = user
                except User.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': 'User not found'})
            
            coupon.save()
            
            return JsonResponse({'status': 'success', 'message': 'Coupon created successfully'})
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

@login_required
@admin_required
def edit_coupon(request, code):
    try:
        coupon = Coupon.objects.get(code=code)
        
        if request.method == 'POST':
            discount_type = request.POST.get('discount_type')
            discount_value = request.POST.get('discount_value')
            min_purchase_amount = request.POST.get('min_purchase_amount')
            expiry_date = request.POST.get('expiry_date')
            is_active = request.POST.get('is_active') == 'true'
            
            # Validate inputs
            if not discount_type or not discount_value or not min_purchase_amount or not expiry_date:
                return JsonResponse({'status': 'error', 'message': 'All fields are required'})
            
            # Convert values to appropriate types
            discount_value = float(discount_value)
            min_purchase_amount = float(min_purchase_amount)
            
            # Update coupon
            coupon.min_purchase_amount = min_purchase_amount
            coupon.expiry_date = expiry_date
            coupon.is_active = is_active
            
            # Set discount based on type
            if discount_type == 'percentage':
                if discount_value > 100:
                    return JsonResponse({'status': 'error', 'message': 'Percentage discount cannot exceed 100%'})
                coupon.discount_percentage = discount_value
                coupon.discount_amount = 0
            else:  # amount
                coupon.discount_amount = discount_value
                coupon.discount_percentage = 0
            
            coupon.save()
            
            return JsonResponse({'status': 'success', 'message': 'Coupon updated successfully'})
        
        # Return coupon details for GET request
        return JsonResponse({
            'status': 'success',
            'coupon': {
                'code': coupon.code,
                'discount_type': 'percentage' if coupon.discount_percentage > 0 else 'amount',
                'discount_value': coupon.discount_percentage if coupon.discount_percentage > 0 else coupon.discount_amount,
                'min_purchase_amount': coupon.min_purchase_amount,
                'expiry_date': coupon.expiry_date.strftime('%Y-%m-%d'),
                'is_active': coupon.is_active,
                'user': coupon.user.id if coupon.user else None,
                'is_used': coupon.is_used,
            }
        })
        
    except Coupon.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Coupon not found'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
@admin_required
def delete_coupon(request, code):
    if request.method == 'POST':
        try:
            coupon = Coupon.objects.get(code=code)
            
            # Check if coupon is used
            if coupon.is_used:
                return JsonResponse({'status': 'error', 'message': 'Cannot delete a coupon that has been used'})
            
            coupon.delete()
            return JsonResponse({'status': 'success', 'message': 'Coupon deleted successfully'})
            
        except Coupon.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Coupon not found'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

@login_required
@admin_required
def generate_coupon_for_user(request, user_id):
    if request.method == 'POST':
        try:
            user = User.objects.get(id=user_id)
            
            # Generate a unique coupon code
            import random
            import string
            
            def generate_code():
                return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            
            code = generate_code()
            # Check for case-insensitive duplicates
            while Coupon.objects.filter(code__iexact=code).exists():
                code = generate_code()
            
            # Get coupon details from request
            discount_type = request.POST.get('discount_type')
            discount_value = float(request.POST.get('discount_value', 0))
            min_purchase_amount = float(request.POST.get('min_purchase_amount', 0))
            expiry_days = int(request.POST.get('expiry_days', 30))
            
            # Calculate expiry date
            expiry_date = timezone.now() + timezone.timedelta(days=expiry_days)
            
            # Create coupon
            coupon = Coupon()
            coupon.code = code
            coupon.user = user
            coupon.min_purchase_amount = min_purchase_amount
            coupon.expiry_date = expiry_date
            coupon.is_admin_generated = True  # Mark as admin generated
            
            # Set discount based on type
            if discount_type == 'percentage':
                if discount_value > 100:
                    return JsonResponse({'status': 'error', 'message': 'Percentage discount cannot exceed 100%'})
                coupon.discount_percentage = discount_value
                coupon.discount_amount = 0
            else:  # amount
                coupon.discount_amount = discount_value
                coupon.discount_percentage = 0
            
            coupon.save()
            
            return JsonResponse({
                'status': 'success', 
                'message': f'Coupon {code} generated successfully for {user.username}',
                'coupon': {
                    'code': code,
                    'discount': f"{discount_value}{'%' if discount_type == 'percentage' else '₹'}",
                    'expiry_date': expiry_date.strftime('%Y-%m-%d')
                }
            })
            
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'User not found'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

@login_required(login_url='admin_side:admin_login')
def sales_data_view(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    period = request.GET.get('period', 'daily')
    today = timezone.now().date()
    
    if period == 'daily':
        # Last 7 days data
        days = 7
        end_date = today
        start_date = end_date - timedelta(days=days-1)
        
        sales_data = Order.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status__in=['DELIVERED', 'SHIPPED']
        ).annotate(
            day=TruncDay('created_at')
        ).values('day').annotate(
            total=Sum('total')
        ).order_by('day')
        
        # Create a dictionary with all dates in range
        date_range = {(start_date + timedelta(days=i)).strftime('%Y-%m-%d'): 0 for i in range(days)}
        
        # Fill in actual values
        for entry in sales_data:
            date_key = entry['day'].strftime('%Y-%m-%d')
            date_range[date_key] = float(entry['total'])
        
        labels = [datetime.strptime(date, '%Y-%m-%d').strftime('%d %b') for date in date_range.keys()]
        data = list(date_range.values())
        
    elif period == 'weekly':
        # Last 12 weeks data
        weeks = 12
        end_date = today
        start_date = end_date - timedelta(weeks=weeks)
        
        # Group by week
        sales_data = []
        for i in range(weeks):
            week_start = end_date - timedelta(weeks=i+1)
            week_end = end_date - timedelta(weeks=i)
            
            week_total = Order.objects.filter(
                created_at__date__gt=week_start,
                created_at__date__lte=week_end,
                status__in=['DELIVERED', 'SHIPPED']
            ).aggregate(total=Sum('total'))['total'] or 0
            
            sales_data.append({
                'week': f"Week {weeks-i}",
                'total': week_total
            })
        
        sales_data.reverse()
        labels = [entry['week'] for entry in sales_data]
        data = [float(entry['total']) for entry in sales_data]
        
    elif period == 'monthly':
        # Last 12 months data
        months = 12
        
        sales_data = Order.objects.filter(
            created_at__date__gte=today.replace(day=1) - timedelta(days=365),
            status__in=['DELIVERED', 'SHIPPED']
        ).annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            total=Sum('total')
        ).order_by('month')
        
        # Create a dictionary with all months in range
        month_range = {}
        for i in range(months):
            month_date = today.replace(day=1) - timedelta(days=30*i)
            month_range[month_date.strftime('%Y-%m')] = 0
        
        # Fill in actual values
        for entry in sales_data:
            month_key = entry['month'].strftime('%Y-%m')
            if month_key in month_range:
                month_range[month_key] = float(entry['total'])
        
        # Sort by date
        sorted_months = sorted(month_range.items(), key=lambda x: x[0])
        labels = [datetime.strptime(m[0], '%Y-%m').strftime('%b %Y') for m in sorted_months]
        data = [m[1] for m in sorted_months]
    
    return JsonResponse({
        'labels': labels,
        'data': data
    })

@login_required(login_url='admin_side:admin_login')
def export_sales_data(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Get filter parameters
    time_range = request.GET.get('time_range', 'month')
    category_id = request.GET.get('category', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Set date range based on filters
    today = timezone.now().date()
    if start_date and end_date:
        # Custom date range
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        date_filter = Q(created_at__date__gte=start_date) & Q(created_at__date__lte=end_date)
        date_range_str = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
    else:
        # Predefined ranges
        if time_range == 'today':
            date_filter = Q(created_at__date=today)
            date_range_str = today.strftime('%Y-%m-%d')
        elif time_range == 'week':
            week_ago = today - timedelta(days=7)
            date_filter = Q(created_at__date__gte=week_ago)
            date_range_str = f"{week_ago.strftime('%Y-%m-%d')} to {today.strftime('%Y-%m-%d')}"
        elif time_range == 'month':
            month_ago = today - timedelta(days=30)
            date_filter = Q(created_at__date__gte=month_ago)
            date_range_str = f"{month_ago.strftime('%Y-%m-%d')} to {today.strftime('%Y-%m-%d')}"
        elif time_range == 'year':
            year_ago = today - timedelta(days=365)
            date_filter = Q(created_at__date__gte=year_ago)
            date_range_str = f"{year_ago.strftime('%Y-%m-%d')} to {today.strftime('%Y-%m-%d')}"
        else:  # all time
            date_filter = Q()
            date_range_str = "All Time"
    
    # Apply category filter if specified
    if category_id:
        category_filter = Q(items__product__category_id=category_id)
        category_name = Category.objects.get(id=category_id).name
    else:
        category_filter = Q()
        category_name = "All Categories"
    
    # Get orders with filters applied
    orders = Order.objects.filter(
        date_filter & category_filter
    ).annotate(
        items_count=Count('items')
    ).filter(
        items_count__gt=0
    ).select_related('user').prefetch_related('items__product')
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="sales_data_{today.strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['BookNest Sales Report'])
    writer.writerow([f'Date Range: {date_range_str}'])
    writer.writerow([f'Category: {category_name}'])
    writer.writerow([])
    writer.writerow(['Order ID', 'Date', 'Customer', 'Items', 'Total', 'Status'])
    
    for order in orders:
        writer.writerow([
            order.order_id,
            order.created_at.strftime('%Y-%m-%d %H:%M'),
            order.user.get_full_name() or order.user.username,
            order.items.count(),
            order.total,
            order.status
        ])
    
    writer.writerow([])
    writer.writerow(['Summary'])
    writer.writerow(['Total Orders', orders.count()])
    writer.writerow(['Total Sales', orders.filter(status__in=['DELIVERED', 'SHIPPED']).aggregate(Sum('total'))['total__sum'] or 0])
    writer.writerow(['Pending Orders', orders.filter(status='PENDING').count()])
    writer.writerow(['Shipped Orders', orders.filter(status='SHIPPED').count()])
    writer.writerow(['Delivered Orders', orders.filter(status='DELIVERED').count()])
    writer.writerow(['Cancelled Orders', orders.filter(status='CANCELLED').count()])
    
    return response

# Helper function to expire referral reward coupon
def expire_referral_reward_coupon(order):
    """
    Expire the referral reward coupon associated with an order
    
    Args:
        order: The order object
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if there's a referral reward coupon mentioned in the order notes
        if order.notes and "Referral reward coupon created:" in order.notes:
            # Extract the coupon code from the notes
            coupon_code = order.notes.split("Referral reward coupon created:")[1].strip()
            
            # Find the coupon
            try:
                coupon = Coupon.objects.get(code=coupon_code)
                
                # Expire the coupon
                coupon.is_active = False
                coupon.save()
                
                return True
            except Coupon.DoesNotExist:
                print(f"Coupon with code {coupon_code} not found")
                return False
        
        return False
    except Exception as e:
        print(f"Error expiring referral reward coupon: {str(e)}")
        return False

def clean_pending_refund_transactions(order):
    """
    Clean up any pending refund transactions for an order
    This helps prevent duplicate refunds
    """
    try:
        wallet = Wallet.objects.get(user=order.user)
        # Delete any pending refund transactions for this order
        pending_transactions = WalletTransaction.objects.filter(
            wallet=wallet,
            reference_id=order.order_id,
            transaction_type='CREDIT',
            status='PENDING',
            description__contains='Refund for'
        )
        
        if pending_transactions.exists():
            count = pending_transactions.count()
            pending_transactions.delete()
            return count
        return 0
    except Wallet.DoesNotExist:
        return 0
    except Exception as e:
        print(f"Error cleaning pending transactions: {str(e)}")
        return 0

def clean_duplicate_refund_transactions(order):
    """
    Clean up duplicate completed refund transactions for an order
    Keeps the oldest transaction and removes any duplicates
    """
    try:
        wallet = Wallet.objects.get(user=order.user)
        # Find all completed refund transactions for this order
        completed_transactions = WalletTransaction.objects.filter(
            wallet=wallet,
            reference_id=order.order_id,
            transaction_type='CREDIT',
            status='COMPLETED',
            description__contains='Refund for'
        ).order_by('created_at')
        
        # If there's more than one transaction, keep the first one and delete the rest
        if completed_transactions.count() > 1:
            # Get the first (oldest) transaction
            first_transaction = completed_transactions.first()
            
            # Delete all other transactions
            duplicates = completed_transactions.exclude(id=first_transaction.id)
            duplicate_count = duplicates.count()
            
            # Calculate the total amount to deduct from the wallet
            total_to_deduct = sum(t.amount for t in duplicates)
            
            # Deduct the duplicate amounts from the wallet
            if total_to_deduct > 0:
                wallet.balance -= total_to_deduct
                wallet.save()
            
            # Delete the duplicates
            duplicates.delete()
            
            return duplicate_count, total_to_deduct
        return 0, Decimal('0.00')
    except Wallet.DoesNotExist:
        return 0, Decimal('0.00')
    except Exception as e:
        print(f"Error cleaning duplicate transactions: {str(e)}")
        return 0, Decimal('0.00')

@login_required(login_url='admin_side:admin_login')
def clean_order_refunds(request, order_id):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    order = get_object_or_404(Order, order_id=order_id)
    
    try:
        # Clean up pending transactions
        pending_count = clean_pending_refund_transactions(order)
        
        # Clean up duplicate completed transactions
        duplicate_count, total_deducted = clean_duplicate_refund_transactions(order)
        
        if pending_count > 0 or duplicate_count > 0:
            messages.success(
                request, 
                f'Successfully cleaned up {pending_count} pending and {duplicate_count} duplicate refund transactions. '
                f'Wallet balance adjusted by ₹{total_deducted}.'
            )
        else:
            messages.info(request, 'No duplicate or pending refund transactions found for this order.')
            
    except Exception as e:
        messages.error(request, f'Error cleaning up refund transactions: {str(e)}')
    
    return redirect('admin_side:order_details', order_id=order_id)

@login_required(login_url='admin_side:admin_login')
def wallet_history(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Get filter parameters
    user_filter = request.GET.get('user', '')
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Start with all transactions
    transactions = WalletTransaction.objects.all().select_related('wallet__user').order_by('-created_at')
    
    # Apply user filter
    if user_filter:
        transactions = transactions.filter(
            Q(wallet__user__username__icontains=user_filter) |
            Q(wallet__user__email__icontains=user_filter) |
            Q(wallet__user__first_name__icontains=user_filter) |
            Q(wallet__user__last_name__icontains=user_filter)
        )
    
    # Apply transaction type filter
    if type_filter:
        transactions = transactions.filter(transaction_type=type_filter)
    
    # Apply status filter
    if status_filter:
        transactions = transactions.filter(status=status_filter)
    
    # Apply date range filter
    if date_from:
        try:
            date_from = timezone.datetime.strptime(date_from, '%Y-%m-%d')
            transactions = transactions.filter(created_at__gte=date_from)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to = timezone.datetime.strptime(date_to, '%Y-%m-%d')
            # Add one day to include the end date
            date_to = date_to + timezone.timedelta(days=1)
            transactions = transactions.filter(created_at__lt=date_to)
        except ValueError:
            pass
    
    # Calculate statistics
    total_credit = WalletTransaction.objects.filter(
        transaction_type='CREDIT',
        status='COMPLETED'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    total_debit = WalletTransaction.objects.filter(
        transaction_type='DEBIT',
        status='COMPLETED'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    # Pagination
    paginator = Paginator(transactions, 20)  # Show 20 transactions per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'transactions': page_obj,
        'total_credit': total_credit,
        'total_debit': total_debit,
        'user_filter': user_filter,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'date_from': date_from.strftime('%Y-%m-%d') if isinstance(date_from, timezone.datetime) else '',
        'date_to': (date_to - timezone.timedelta(days=1)).strftime('%Y-%m-%d') if isinstance(date_to, timezone.datetime) else '',
        'transaction_types': WalletTransaction.TRANSACTION_TYPES,
        'transaction_statuses': WalletTransaction.TRANSACTION_STATUS,
    }
    
    return render(request, 'wallet_history.html', context)

@login_required(login_url='admin_side:admin_login')
def update_wallet_transaction(request, transaction_id):
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    try:
        transaction = get_object_or_404(WalletTransaction, id=transaction_id)
        new_status = request.POST.get('status')
        
        if new_status not in [status[0] for status in WalletTransaction.TRANSACTION_STATUS]:
            return JsonResponse({'success': False, 'message': 'Invalid status'})
        
        # If changing from PENDING to COMPLETED for a CREDIT transaction, add the amount to the wallet
        if transaction.status == 'PENDING' and new_status == 'COMPLETED' and transaction.transaction_type == 'CREDIT':
            transaction.wallet.balance += transaction.amount
            transaction.wallet.save()
        
        # If changing from COMPLETED to FAILED/PENDING for a CREDIT transaction, subtract the amount from the wallet
        elif transaction.status == 'COMPLETED' and new_status != 'COMPLETED' and transaction.transaction_type == 'CREDIT':
            if transaction.wallet.balance >= transaction.amount:
                transaction.wallet.balance -= transaction.amount
                transaction.wallet.save()
            else:
                return JsonResponse({
                    'success': False, 
                    'message': 'Insufficient wallet balance to revert this transaction'
                })
        
        # Update the transaction status
        transaction.status = new_status
        transaction.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Transaction status updated to {new_status}',
            'new_status': new_status,
            'new_wallet_balance': str(transaction.wallet.balance)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required(login_url='admin_side:admin_login')
def export_wallet_transactions(request):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Get filter parameters
    user_filter = request.GET.get('user', '')
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Start with all transactions
    transactions = WalletTransaction.objects.all().select_related('wallet__user').order_by('-created_at')
    
    # Apply user filter
    if user_filter:
        transactions = transactions.filter(
            Q(wallet__user__username__icontains=user_filter) |
            Q(wallet__user__email__icontains=user_filter) |
            Q(wallet__user__first_name__icontains=user_filter) |
            Q(wallet__user__last_name__icontains=user_filter)
        )
    
    # Apply transaction type filter
    if type_filter:
        transactions = transactions.filter(transaction_type=type_filter)
    
    # Apply status filter
    if status_filter:
        transactions = transactions.filter(status=status_filter)
    
    # Apply date range filter
    if date_from:
        try:
            date_from = timezone.datetime.strptime(date_from, '%Y-%m-%d')
            transactions = transactions.filter(created_at__gte=date_from)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to = timezone.datetime.strptime(date_to, '%Y-%m-%d')
            # Add one day to include the end date
            date_to = date_to + timezone.timedelta(days=1)
            transactions = transactions.filter(created_at__lt=date_to)
        except ValueError:
            pass
    
    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="wallet_transactions_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Transaction ID', 'Date', 'User', 'Email', 'Description', 'Reference ID', 'Amount', 'Type', 'Status'])
    
    for transaction in transactions:
        writer.writerow([
            transaction.id,
            transaction.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            transaction.wallet.user.get_full_name() or transaction.wallet.user.username,
            transaction.wallet.user.email,
            transaction.description,
            transaction.reference_id or '',
            transaction.amount,
            transaction.get_transaction_type_display(),
            transaction.get_status_display()
        ])
    
    return response

@login_required(login_url='admin_side:admin_login')
def admin_transaction_history_view(request):
    # Get filter parameters from request
    transaction_type = request.GET.get('transaction_type', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    user_search = request.GET.get('user_search', '')
    
    # Initialize empty lists for different transaction types
    wallet_transactions = []
    order_transactions = []
    
    # Convert date strings to datetime objects if provided
    if date_from:
        date_from = datetime.strptime(date_from, '%Y-%m-%d')
    if date_to:
        date_to = datetime.strptime(date_to, '%Y-%m-%d')
        # Add one day to include the entire day
        date_to = date_to + timedelta(days=1)
    
    # Get wallet transactions if needed
    if not transaction_type or transaction_type == 'wallet':
        wallet_query = WalletTransaction.objects.select_related('wallet__user').filter(
            ~Q(status='PENDING')  # Exclude PENDING transactions
        )
        
        # Apply date filters if provided
        if date_from:
            wallet_query = wallet_query.filter(created_at__gte=date_from)
        if date_to:
            wallet_query = wallet_query.filter(created_at__lt=date_to)
            
        # Apply user search if provided
        if user_search:
            wallet_query = wallet_query.filter(
                Q(wallet__user__username__icontains=user_search) |
                Q(wallet__user__email__icontains=user_search)
            )
            
        # Process wallet transactions to match the common format
        for transaction in wallet_query:
            wallet_transactions.append({
                'id': f"W-{transaction.id}",
                'user': transaction.wallet.user,
                'created_at': transaction.created_at,
                'type': 'wallet',
                'transaction_type': transaction.transaction_type,
                'amount': transaction.amount,
                'status': transaction.status,
                'description': transaction.description,
                'source': 'wallet',
                'order_id': transaction.reference_id
            })
    
    # Get order transactions (online and COD) if needed
    if not transaction_type or transaction_type == 'online' or transaction_type == 'cod':
        order_query = Order.objects.select_related('user').filter(
            ~Q(payment_status='PENDING')  # Exclude PENDING transactions
        )
        
        # Apply specific payment method filter if needed
        if transaction_type == 'online':
            order_query = order_query.filter(
                Q(payment_method__icontains='online') | 
                Q(payment_method__icontains='razorpay') |
                Q(payment_method__icontains='wallet')
            ).exclude(
                Q(payment_method__icontains='cod') | 
                Q(payment_method='Cash On Delivery')
            )
        elif transaction_type == 'cod':
            order_query = order_query.filter(
                Q(payment_method__icontains='cod') | 
                Q(payment_method='Cash On Delivery')
            )
            
        # Apply date filters if provided
        if date_from:
            order_query = order_query.filter(created_at__gte=date_from)
        if date_to:
            order_query = order_query.filter(created_at__lt=date_to)
            
        # Apply user search if provided
        if user_search:
            order_query = order_query.filter(
                Q(user__username__icontains=user_search) |
                Q(user__email__icontains=user_search)
            )
            
        # Process order transactions to match the common format
        for order in order_query:
            # Improve payment type detection logic
            payment_type = 'cod' if 'cod' in order.payment_method.lower() or order.payment_method == 'Cash On Delivery' else 'online'
            order_transactions.append({
                'id': f"O-{order.id}",
                'user': order.user,
                'created_at': order.created_at,
                'type': payment_type,
                'transaction_type': order.payment_method,
                'amount': order.total,
                'status': order.payment_status,
                'description': f"Order #{order.order_id}",
                'source': 'order',
                'order_id': order.order_id
            })
    
    # Combine all transactions and sort by date (newest first)
    all_transactions = wallet_transactions + order_transactions
    all_transactions.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Paginate the results
    paginator = Paginator(all_transactions, 20)  # Show 20 transactions per page
    page = request.GET.get('page', 1)
    transactions = paginator.get_page(page)
    
    context = {
        'transactions': transactions,
        'transaction_type': transaction_type,
        'date_from': date_from,
        'date_to': date_to if date_to else None,
        'user_search': user_search,
    }
    
    return render(request, 'transaction_history.html', context)

@login_required(login_url='admin_side:admin_login')
def approve_item_return(request, order_id):
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    try:
        with transaction.atomic():
            order = get_object_or_404(Order, order_id=order_id)
            item_id = request.POST.get('item_id')
            condition = request.POST.get('condition', '')
            notes = request.POST.get('notes', '')
            
            if not item_id:
                return JsonResponse({'success': False, 'message': 'Item ID is required'})
            
            # Get the specific item
            order_item = get_object_or_404(OrderItem, id=item_id, order=order)
            
            # Check if item return was requested
            if order_item.status != 'RETURN_REQUESTED':
                return JsonResponse({'success': False, 'message': 'No return request found for this item'})
            
            # Update item status
            order_item.status = 'RETURNED'
            order_item.save()
            
            # Increment product stock for the returned item
            product = order_item.product
            product.stock += order_item.quantity
            product.save()
            
            # Process refund through wallet
            wallet, created = Wallet.objects.get_or_create(user=order.user)
            
            # Calculate refund amount for this item
            refund_amount = order_item.total
            
            # Check if a completed refund transaction already exists for this item
            existing_refund = WalletTransaction.objects.filter(
                wallet=wallet,
                reference_id=f"{order.order_id}-{order_item.id}",
                transaction_type='CREDIT',
                status='COMPLETED'
            ).exists()
            
            if not existing_refund:
                # Add refund amount to wallet
                wallet.balance += refund_amount
                wallet.save()
                
                # Create wallet transaction record
                WalletTransaction.objects.create(
                    wallet=wallet,
                    amount=refund_amount,
                    transaction_type='CREDIT',
                    status='COMPLETED',
                    description=f'Refund for returned item {order_item.product.title} (Order #{order.order_id})',
                    reference_id=f"{order.order_id}-{order_item.id}"
                )
                
                # Delete any pending transactions for this item
                WalletTransaction.objects.filter(
                    wallet=wallet,
                    reference_id=f"{order.order_id}-{order_item.id}",
                    transaction_type='CREDIT',
                    status='PENDING'
                ).delete()
            
            # Update order notes
            note_prefix = f"Item Return Approved [{timezone.now().strftime('%Y-%m-%d %H:%M')}]: "
            item_note = f"Item '{order_item.product.title}' return approved. Condition: {condition}. Notes: {notes}"
            
            if order.notes:
                order.notes = order.notes + "\n" + note_prefix + item_note
            else:
                order.notes = note_prefix + item_note
            
            # Check if all items have been returned or rejected
            all_items_returned = True
            for item in order.items.all():
                if item.status not in ['RETURNED', 'RETURN_REJECTED']:
                    all_items_returned = False
                    break
            
            # If all items have been processed, update order status
            if all_items_returned:
                order.status = 'RETURNED'
                order.returned_at = timezone.now()
                order.return_requested = False
            
            order.save()
            
            return JsonResponse({'success': True, 'message': f'Item return approved and ₹{refund_amount} refunded to user\'s wallet'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required(login_url='admin_side:admin_login')
def reject_item_return(request, order_id):
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    try:
        with transaction.atomic():
            order = get_object_or_404(Order, order_id=order_id)
            item_id = request.POST.get('item_id')
            notes = request.POST.get('notes', '')
            
            if not item_id:
                return JsonResponse({'success': False, 'message': 'Item ID is required'})
            
            # Get the specific item
            order_item = get_object_or_404(OrderItem, id=item_id, order=order)
            
            # Check if item return was requested
            if order_item.status != 'RETURN_REQUESTED':
                return JsonResponse({'success': False, 'message': 'No return request found for this item'})
            
            # Update item status
            order_item.status = 'RETURN_REJECTED'
            order_item.save()
            
            # Delete any pending transactions for this item
            wallet = Wallet.objects.filter(user=order.user).first()
            if wallet:
                WalletTransaction.objects.filter(
                    wallet=wallet,
                    reference_id=f"{order.order_id}-{order_item.id}",
                    transaction_type='CREDIT',
                    status='PENDING'
                ).delete()
            
            # Update order notes
            note_prefix = f"Item Return Rejected [{timezone.now().strftime('%Y-%m-%d %H:%M')}]: "
            item_note = f"Item '{order_item.product.title}' return rejected. Reason: {notes}"
            
            if order.notes:
                order.notes = order.notes + "\n" + note_prefix + item_note
            else:
                order.notes = note_prefix + item_note
            
            # Check if all items have been returned or rejected
            all_items_processed = True
            for item in order.items.all():
                if item.status == 'RETURN_REQUESTED':
                    all_items_processed = False
                    break
            
            # If all items have been processed, update order status
            if all_items_processed:
                order.return_requested = False
                if all(item.status == 'RETURN_REJECTED' for item in order.items.all()):
                    # If all were rejected, set order back to delivered
                    order.status = 'DELIVERED'
                
            order.save()
            
            return JsonResponse({'success': True, 'message': 'Item return rejected successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required(login_url='admin_side:admin_login')
def reviews_management(request):
    """
    View to display and manage all product reviews
    """
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    # Get filter parameters
    rating = request.GET.get('rating', '')
    product_id = request.GET.get('product', '')
    date_range = request.GET.get('date_range', '')
    verified_only = request.GET.get('verified', '')
    search_query = request.GET.get('search', '')
    
    # Base query
    reviews = Review.objects.all().select_related('user', 'product')
    
    # Apply filters
    if rating:
        reviews = reviews.filter(rating=rating)
    
    if product_id:
        reviews = reviews.filter(product_id=product_id)
    
    if verified_only == 'true':
        reviews = reviews.filter(verified_purchase=True)
    
    if date_range:
        today = timezone.now().date()
        if date_range == 'today':
            reviews = reviews.filter(created_at__date=today)
        elif date_range == 'week':
            week_ago = today - timedelta(days=7)
            reviews = reviews.filter(created_at__date__gte=week_ago)
        elif date_range == 'month':
            month_ago = today - timedelta(days=30)
            reviews = reviews.filter(created_at__date__gte=month_ago)
    
    if search_query:
        reviews = reviews.filter(
            Q(comment__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(product__title__icontains=search_query)
        )
    
    # Order by most recent
    reviews = reviews.order_by('-created_at')
    
    # Calculate statistics
    total_reviews = Review.objects.count()
    verified_reviews = Review.objects.filter(verified_purchase=True).count()
    average_rating = Review.objects.aggregate(avg=Avg('rating'))['avg'] or 0
    products_with_reviews = Review.objects.values('product').distinct().count()
    
    # Get all products for filter dropdown
    all_products = Product.objects.filter(status='active').order_by('title')
    
    # Pagination
    paginator = Paginator(reviews, 10)  # 10 reviews per page
    page_number = request.GET.get('page')
    reviews = paginator.get_page(page_number)
    
    context = {
        'reviews': reviews,
        'total_reviews': total_reviews,
        'verified_reviews': verified_reviews,
        'average_rating': average_rating,
        'products_with_reviews': products_with_reviews,
        'all_products': all_products,
    }
    
    return render(request, 'reviews.html', context)

@login_required(login_url='admin_side:admin_login')
def delete_review(request, review_id):
    """
    View to delete a review
    """
    if not request.user.is_superuser:
        messages.error(request, 'Access denied, You are not admin')
        return redirect('admin_side:admin_login')
    
    review = get_object_or_404(Review, id=review_id)
    
    try:
        review.delete()
        messages.success(request, f"Review by {review.user.username} for '{review.product.title}' deleted successfully")
    except Exception as e:
        messages.error(request, f"Failed to delete review: {str(e)}")
    
    return redirect('admin_side:reviews')