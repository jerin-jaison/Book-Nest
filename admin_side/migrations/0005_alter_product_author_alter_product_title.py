# Generated by Django 5.0.2 on 2025-03-07 06:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_side', '0004_alter_product_title'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='author',
            field=models.TextField(),
        ),
        migrations.AlterField(
            model_name='product',
            name='title',
            field=models.TextField(),
        ),
    ]
