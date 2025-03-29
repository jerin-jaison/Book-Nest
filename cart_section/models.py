from django.db import models
from django.contrib.auth.models import User
from admin_side.models import Product
import uuid
from django.utils import timezone

class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'product')  # Prevent duplicate cart items

    def __str__(self):
        return f"{self.user.username}'s Cart - {self.product.title}"

    @property
    def total_price(self):
        return self.quantity * self.product.final_price

    @property
    def is_valid_for_checkout(self):
        return (
            self.product.status == 'active' and
            self.product.category.is_active and
            self.product.stock >= self.quantity
        )

class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    full_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15)
    pincode = models.CharField(max_length=6)
    house_no = models.CharField(max_length=100)
    area = models.CharField(max_length=100)
    landmark = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Addresses'
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.full_name}'s address in {self.city}"

    def save(self, *args, **kwargs):
        # If this is the first address or being set as default
        if self.is_default:
            # Set all other addresses of this user as non-default
            Address.objects.filter(user=self.user).update(is_default=False)
        # If this is the first address for the user, make it default
        elif not Address.objects.filter(user=self.user).exists():
            self.is_default = True
        super().save(*args, **kwargs)

class Order(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
        ('RETURNED', 'Returned'),
        ('RETURN_REQUESTED', 'Return Requested'),
        ('RETURN_REJECTED', 'Return Rejected'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]

    order_id = models.CharField(max_length=10, unique=True, editable=False, null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    address = models.ForeignKey(Address, on_delete=models.PROTECT)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Razorpay fields
    razorpay_order_id = models.CharField(max_length=100, null=True, blank=True)
    payment_id = models.CharField(max_length=100, null=True, blank=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    notes = models.TextField(blank=True, null=True)
    
    # New fields for order management
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    return_reason = models.TextField(blank=True)
    return_details = models.TextField(blank=True)
    return_requested = models.BooleanField(default=False)
    return_requested_at = models.DateTimeField(null=True, blank=True)
    
    def save(self, *args, **kwargs):
        if not self.order_id:
            # Generate a unique order ID
            while True:
                order_id = str(uuid.uuid4().hex)[:10].upper()
                if not Order.objects.filter(order_id=order_id).exists():
                    self.order_id = order_id
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order {self.order_id} by {self.user.username}"

class OrderItem(models.Model):
    STATUS_CHOICES = [
        ('CONFIRMED', 'Confirmed'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
        ('RETURNED', 'Returned'),
        ('RETURN_REQUESTED', 'Return Requested'),
        ('RETURN_REJECTED', 'Return Rejected'),
    ]

    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CONFIRMED')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.quantity}x {self.product.title} in Order {self.order.order_id}"
