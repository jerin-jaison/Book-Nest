from django.db import models
from django.contrib.auth.models import User
from admin_side.models import Product

class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_wishlist')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='user_authentication_wishlist')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')  # Prevent duplicate wishlist items

    def __str__(self):
        return f"{self.user.username}'s wishlist - {self.product.title}"
