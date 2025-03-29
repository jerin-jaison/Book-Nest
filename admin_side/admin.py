from django.contrib import admin
from .models import (
    Customer, Category, Product, ProductImage, 
    ProductOffer, CategoryOffer, ReferralCode, 
    ReferralOffer, ReferralHistory, Coupon, CouponUsage,
    Review
)

# Only register models that are not already registered
try:
    admin.site.register(Customer)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(Category)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(Product)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(ProductImage)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(ProductOffer)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(CategoryOffer)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(ReferralCode)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(ReferralOffer)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(ReferralHistory)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(Coupon)
except admin.sites.AlreadyRegistered:
    pass

try:
    admin.site.register(CouponUsage)
except admin.sites.AlreadyRegistered:
    pass

# Register the new Review model
try:
    admin.site.register(Review)
except admin.sites.AlreadyRegistered:
    pass
