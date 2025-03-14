# admin.py
from django.contrib import admin
from admin_side.models import Category, Product, ProductImage

admin.site.register(Category)
admin.site.register(ProductImage)
admin.site.register(Product)