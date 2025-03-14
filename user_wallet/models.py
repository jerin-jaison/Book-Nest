from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Wallet (₹{self.balance})"

class WalletTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('CREDIT', 'Credit'),
        ('DEBIT', 'Debit'),
    ]

    TRANSACTION_STATUS = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=10, choices=TRANSACTION_STATUS, default='PENDING')
    description = models.TextField()
    reference_id = models.CharField(max_length=100, blank=True, null=True)  # For order IDs or return IDs
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_type} - ₹{self.amount} - {self.status}"
