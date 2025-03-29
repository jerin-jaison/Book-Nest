# models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify

class Customer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_blocked = models.BooleanField(default=False)
    join_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.user.username
    
class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_product_count(self):
        return self.products.count()
    
class Product(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('out_of_stock', 'Out of Stock'),
        ('coming_soon', 'Coming Soon'),
    )
    
    LANGUAGE_CHOICES = (
        ('english', 'English'),
        ('hindi', 'Hindi'),
        ('tamil', 'Tamil'),
        ('telugu', 'Telugu'),
        ('malayalam', 'Malayalam'),
        ('kannada', 'Kannada'),
        ('bengali', 'Bengali'),
        ('marathi', 'Marathi'),
        ('gujarati', 'Gujarati'),
        ('punjabi', 'Punjabi'),
        ('urdu', 'Urdu'),
        ('sanskrit', 'Sanskrit'),
        ('spanish', 'Spanish'),
        ('french', 'French'),
        ('german', 'German'),
        ('chinese', 'Chinese'),
        ('japanese', 'Japanese'),
        ('korean', 'Korean'),
        ('arabic', 'Arabic'),
        ('russian', 'Russian'),
    )

    title = models.TextField()
    slug = models.SlugField(unique=True, blank=True)
    author = models.TextField()
    isbn = models.CharField(max_length=13, unique=True, blank=True, null=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    cover_image = models.ImageField(upload_to='books/covers/')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    publish_year = models.PositiveIntegerField(null=True, blank=True)
    language = models.CharField(max_length=20, choices=LANGUAGE_CHOICES, default='english')
    page_count = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    @property
    def is_discounted(self):
        return bool(self.discount_price and self.discount_price < self.price)

    @property
    def final_price(self):
        # First check if there's a manual discount price set
        if self.is_discounted:
            base_price = self.discount_price
        else:
            base_price = self.price
            
        # Then check if there are any applicable offers
        offer_price = self.get_offer_price()
        if offer_price and offer_price < base_price:
            return offer_price
            
        return base_price
        
    def get_best_offer(self):
        """Returns the best offer applicable to this product"""
        from django.utils import timezone
        now = timezone.now()
        
        # Get all valid product offers
        product_offers = self.offers.filter(
            is_active=True,
            start_date__lte=now,
            end_date__gte=now
        ).order_by('-discount_percentage')
        
        # Get all valid category offers
        category_offers = []
        if self.category:
            category_offers = self.category.offers.filter(
                is_active=True,
                start_date__lte=now,
                end_date__gte=now
            ).order_by('-discount_percentage')
        
        best_offer = None
        best_discount = 0
        
        # Check product offers
        if product_offers.exists():
            best_offer = product_offers.first()
            best_discount = best_offer.discount_percentage
            
        # Check if any category offer is better
        if category_offers.exists():
            category_offer = category_offers.first()
            if best_offer is None or category_offer.discount_percentage > best_discount:
                best_offer = category_offer
                best_discount = category_offer.discount_percentage
                
        return best_offer
    
    def get_offer_price(self):
        """Calculate the price after applying the best offer"""
        best_offer = self.get_best_offer()
        if not best_offer:
            return None
            
        if self.is_discounted:
            base_price = self.discount_price
        else:
            base_price = self.price
            
        discount_amount = (base_price * best_offer.discount_percentage) / 100
        return base_price - discount_amount
        
    def get_offer_details(self):
        """Returns details about the best offer applicable to this product"""
        best_offer = self.get_best_offer()
        if not best_offer:
            return None
            
        if hasattr(best_offer, 'product'):
            offer_type = 'Product Offer'
        else:
            offer_type = 'Category Offer'
            
        return {
            'type': offer_type,
            'title': best_offer.title,
            'discount_percentage': best_offer.discount_percentage,
            'original_price': self.price,
            'final_price': self.get_offer_price()
        }

class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name='additional_images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='books/additional/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.product.title}"

# Offer Management Models
class ProductOffer(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='offers')
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    discount_percentage = models.PositiveIntegerField(help_text="Discount percentage (e.g., 10 for 10% off)")
    is_active = models.BooleanField(default=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.discount_percentage}% off on {self.product.title}"
    
    def is_valid(self):
        from django.utils import timezone
        now = timezone.now()
        return self.is_active and self.start_date <= now <= self.end_date
    
    def get_discounted_price(self):
        """Calculate the discounted price for this product offer"""
        if not hasattr(self, 'product') or not self.product:
            return None
            
        base_price = self.product.discount_price if self.product.discount_price else self.product.price
        discount_amount = (base_price * self.discount_percentage) / 100
        return round(base_price - discount_amount, 2)

class CategoryOffer(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='offers')
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    discount_percentage = models.PositiveIntegerField(help_text="Discount percentage (e.g., 10 for 10% off)")
    is_active = models.BooleanField(default=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.discount_percentage}% off on {self.category.name} category"
    
    def is_valid(self):
        from django.utils import timezone
        now = timezone.now()
        return self.is_active and self.start_date <= now <= self.end_date
    
    def get_discounted_price(self):
        """
        Calculate the discounted price for a product with this category offer.
        Note: This will be called from a product context, so we need to use the product's price.
        """
        # This method will be called from the product template with the product's best offer
        # The actual calculation happens in Product.get_offer_price()

class ReferralCode(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='referral_code')
    code = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Referral code {self.code} for {self.user.username}"

class ReferralOffer(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField()
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Fixed amount discount")
    discount_percentage = models.PositiveIntegerField(null=True, blank=True, help_text="Percentage discount (optional)")
    min_purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        if self.discount_percentage:
            return f"{self.title} - {self.discount_percentage}% off (min purchase: ₹{self.min_purchase_amount})"
        return f"{self.title} - ₹{self.discount_amount} off (min purchase: ₹{self.min_purchase_amount})"
    
    def is_valid(self):
        from django.utils import timezone
        now = timezone.now()
        return self.is_active and self.start_date <= now <= self.end_date

class ReferralHistory(models.Model):
    referrer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='referrals_made')
    referred_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='referred_by')
    referral_code = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    reward_given = models.BooleanField(default=False)
    reward_deducted = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('referrer', 'referred_user')
        
    def __str__(self):
        return f"{self.referrer.username} referred {self.referred_user.username}"

class Coupon(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='coupons', null=True, blank=True)
    code = models.CharField(max_length=20, unique=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    discount_percentage = models.PositiveIntegerField(null=True, blank=True)
    min_purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    expiry_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_admin_generated = models.BooleanField(default=False, help_text='Indicates if this coupon was generated by an admin for a specific user')
    
    def __str__(self):
        user_str = f"for {self.user.username}" if self.user else "(Global)"
        if self.discount_percentage:
            return f"Coupon {self.code} - {self.discount_percentage}% off {user_str}"
        return f"Coupon {self.code} - ₹{self.discount_amount} off {user_str}"
    
    def is_valid(self):
        from django.utils import timezone
        now = timezone.now()
        return self.is_active and now < self.expiry_date
    
    def is_used_by_user(self, user):
        """Check if this coupon has been used by the specified user"""
        return CouponUsage.objects.filter(coupon=self, user=user).exists()
    
    @property
    def is_used(self):
        """Check if this coupon has been used by any user"""
        return self.usages.exists()

class CouponUsage(models.Model):
    """Model to track which users have used which coupons"""
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='usages')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='coupon_usages')
    order = models.ForeignKey('cart_section.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='coupon_usages')
    used_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('coupon', 'user')
        verbose_name_plural = "Coupon Usages"
    
    def __str__(self):
        return f"{self.user.username} used {self.coupon.code}"

class Review(models.Model):
    RATING_CHOICES = (
        (1, '1 - Poor'),
        (2, '2 - Fair'),
        (3, '3 - Good'),
        (4, '4 - Very Good'),
        (5, '5 - Excellent')
    )
    
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Track if the review is from a verified purchase
    verified_purchase = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ('product', 'user')
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.user.username}'s review of {self.product.title}"
