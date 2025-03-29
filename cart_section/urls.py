from django.urls import path
from . import views

app_name = 'cart_section'

urlpatterns = [
    path('', views.view_cart, name='view_cart'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('update-quantity/<int:cart_item_id>/', views.update_quantity, name='update_quantity'),
    path('remove/<int:cart_item_id>/', views.remove_from_cart, name='remove_from_cart'),
    
    # Checkout URLs
    path('checkout/', views.checkout, name='checkout'),
    path('place-order/', views.place_order, name='place_order'),
    path('buy-now/<int:product_id>/', views.buy_now, name='buy_now'),
    
    # Address management URLs
    path('address/add/', views.add_address, name='add_address'),
    path('address/<int:address_id>/', views.get_address, name='get_address'),
    path('address/update/<int:address_id>/', views.update_address, name='update_address'),
    path('address/make-default/<int:address_id>/', views.make_default_address, name='make_default_address'),
    path('address/delete/<int:address_id>/', views.delete_address, name='delete_address'),

    path('order_placed/', views.order_placed, name='order_placed'),
    
    # Coupon URLs
    path('apply-coupon/', views.apply_coupon, name='apply_coupon'),
    path('remove-coupon/', views.remove_coupon, name='remove_coupon'),
    
    # Order retry payment URL
    path('retry-payment/<str:order_id>/', views.retry_payment, name='retry_payment'),
    
    # Catch undefined checkout URLs and redirect to order_placed
    path('checkout/<path:undefined_path>', views.handle_undefined_checkout, name='handle_undefined_checkout'),
]