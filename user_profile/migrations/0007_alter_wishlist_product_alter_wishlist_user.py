# Generated by Django 5.1.3 on 2025-03-03 11:55

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_side', '0004_alter_product_title'),
        ('user_profile', '0006_wishlist'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='wishlist',
            name='product',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_profile_wishlist', to='admin_side.product'),
        ),
        migrations.AlterField(
            model_name='wishlist',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_profile_wishlist', to=settings.AUTH_USER_MODEL),
        ),
    ]
