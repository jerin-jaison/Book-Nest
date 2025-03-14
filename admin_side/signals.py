# signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import Customer

@receiver(post_save, sender=User)
def create_customer(sender, instance, created, **kwargs):
    if created and not instance.is_superuser:
        Customer.objects.create(user=instance)