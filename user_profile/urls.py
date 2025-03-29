from django.urls import path
from . import views

app_name = 'user_profile'

urlpatterns = [
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/detail/', views.acc_detail, name='acc_detail'),
    path('profile/address/', views.address_view, name='address'),
    path('verify-email-otp/', views.verify_email_otp, name='verify_email_otp'),
    path('change-password/', views.change_password, name='change_password'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('verify-password-otp/', views.verify_password_otp, name='verify_password_otp'),
    path('reset-password/', views.reset_password, name='reset_password'),
    
    # Order management URLs
    path('orders/', views.orders_list, name='orders_list'),
    path('orders/<str:order_id>/', views.order_detail, name='order_detail'),
    path('orders/<str:order_id>/cancel/', views.cancel_order_page, name='cancel_order_page'),
    path('orders/<str:order_id>/cancel/confirm/', views.cancel_order, name='cancel_order'),
    path('orders/<str:order_id>/return/', views.return_order, name='return_order'),
    path('orders/<str:order_id>/return/cancel/', views.cancel_return_request, name='cancel_return_request'),
    path('orders/<str:order_id>/return-item/', views.return_item, name='return_item'),
    path('orders/<str:order_id>/invoice/', views.generate_invoice, name='generate_invoice'),
    path('get_item_rejection_reason/<int:item_id>/', views.get_item_rejection_reason, name='get_item_rejection_reason'),
    path('wishlist/', views.wishlist_view, name='wishlist'),
    path('wishlist/toggle/<int:product_id>/', views.toggle_wishlist, name='toggle_wishlist'),
    
    # Coupons and Referrals
    path('coupons/', views.my_coupons, name='my_coupons'),
]