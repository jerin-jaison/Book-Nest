from django.db import models
from django.contrib.auth.models import User
from admin_side.models import Product
from cart_section.models import Product

class AccountDetails(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='account_details')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    profile_image = models.ImageField(upload_to='profile_images/', null=True, blank=True)
    email_verified = models.BooleanField(default=False)
    email_otp = models.CharField(max_length=6, null=True, blank=True)
    email_otp_timestamp = models.DateTimeField(null=True, blank=True)
    pending_email = models.EmailField(null=True, blank=True)  # Store the email that's being verified
    
    # New address fields
    house_name = models.CharField(max_length=100, blank=True)
    landmark = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pin_code = models.CharField(max_length=6, blank=True)
    country = models.CharField(max_length=100, default='India')

    def __str__(self):
        return f"{self.user.username}'s Account Details"

class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_profile_wishlist')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='user_profile_wishlist')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')

    def __str__(self):
        return f"{self.user.username}'s wishlist item: {self.product.title}"

class WishlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.user.username}'s wishlist - {self.product.title}"
