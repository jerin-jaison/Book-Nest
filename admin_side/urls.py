from django.urls import path
from . import views

app_name = 'admin_side'

urlpatterns = [
    path('admin_login/', views.admin_login_view, name='admin_login'),
    path('admin_home/', views.admin_home_view, name='admin_home'),
    path('admin_logout/', views.admin_logout_view, name='admin_logout'),
    path('customer_management/', views.admin_customers_view, name='customer_management'),
    path('block_user/<int:user_id>/', views.admin_blockUser_view, name='block_user'),
    path('unblock_user/<int:user_id>/', views.admin_unblockUser_view, name='unblock_user'),
    
    # Dashboard Data URLs
    path('sales-data/', views.sales_data_view, name='sales_data'),
    path('export-sales/', views.export_sales_data, name='export_sales'),
    
    # Product Management URLs
    path('products/', views.product_list_view, name='product_list'),
    path('product/add/', views.add_product_view, name='add_product'),
    path('product/edit/<int:product_id>/', views.edit_product_view, name='edit_product'),
    path('product/delete/<int:product_id>/', views.delete_product, name='delete_product'),
    path('product/delete-image/<int:image_id>/', views.delete_product_image, name='delete_product_image'),
    
    # Category Management URLs
    path('categories/', views.category_management, name='category_management'),
    path('categories/add/', views.add_category, name='add_category'),
    path('categories/edit/<int:category_id>/', views.edit_category, name='edit_category'),
    path('categories/delete/<int:category_id>/', views.delete_category, name='delete_category'),

    # Order Management URLs
    path('orders/', views.order_management, name='order_management'),
    path('orders/<str:order_id>/details/', views.order_details, name='order_details'),
    path('orders/<str:order_id>/status/', views.update_order_status, name='update_order_status'),
    path('orders/<str:order_id>/return-details/', views.get_return_details, name='get_return_details'),
    path('orders/<str:order_id>/process-return/', views.process_return, name='process_return'),
    path('orders/<str:order_id>/approve-return/', views.approve_return, name='approve_return'),
    path('orders/<str:order_id>/reject-return/', views.reject_return, name='reject_return'),
    path('orders/<str:order_id>/approve-item-return/', views.approve_item_return, name='approve_item_return'),
    path('orders/<str:order_id>/reject-item-return/', views.reject_item_return, name='reject_item_return'),
    path('orders/<str:order_id>/clean-refunds/', views.clean_order_refunds, name='clean_order_refunds'),
    path('orders/export/', views.export_orders, name='export_orders'),
    
    # Review Management URLs
    path('reviews/', views.reviews_management, name='reviews'),
    path('reviews/delete/<int:review_id>/', views.delete_review, name='delete_review'),
    
    # Inventory Management URLs
    path('products/<int:product_id>/update-stock/', views.update_stock, name='update_stock'),
    path('inventory/', views.inventory_management, name='inventory_management'),
    path('inventory/low-stock/', views.low_stock_alerts, name='low_stock_alerts'),

    # Offer Management URLs
    path('offers/', views.offer_management, name='offer_management'),
    
    # Product Offer URLs
    path('offers/products/', views.product_offer_list, name='product_offer_list'),
    path('offers/products/add/', views.add_product_offer, name='add_product_offer'),
    path('offers/products/edit/<int:offer_id>/', views.edit_product_offer, name='edit_product_offer'),
    path('offers/products/delete/<int:offer_id>/', views.delete_product_offer, name='delete_product_offer'),
    
    # Category Offer URLs
    path('offers/categories/', views.category_offer_list, name='category_offer_list'),
    path('offers/categories/add/', views.add_category_offer, name='add_category_offer'),
    path('offers/categories/edit/<int:offer_id>/', views.edit_category_offer, name='edit_category_offer'),
    path('offers/categories/delete/<int:offer_id>/', views.delete_category_offer, name='delete_category_offer'),
    
    # Referral Offer URLs
    path('offers/referrals/', views.referral_offer_list, name='referral_offer_list'),
    path('offers/referrals/add/', views.add_referral_offer, name='add_referral_offer'),
    path('offers/referrals/edit/<int:offer_id>/', views.edit_referral_offer, name='edit_referral_offer'),
    path('offers/referrals/delete/<int:offer_id>/', views.delete_referral_offer, name='delete_referral_offer'),
    path('offers/referrals/history/', views.referral_history, name='referral_history'),
    
    # Referral Code Management
    path('users/<int:user_id>/generate-referral-code/', views.generate_referral_code, name='generate_referral_code'),
    path('offers/referrals/give-reward/<int:referral_id>/', views.give_referral_reward, name='give_referral_reward'),

    # Coupon Management URLs
    path('coupons/', views.coupon_management, name='coupon_management'),
    path('coupons/create/', views.create_coupon, name='create_coupon'),
    path('coupons/edit/<str:code>/', views.edit_coupon, name='edit_coupon'),
    path('coupons/delete/<str:code>/', views.delete_coupon, name='delete_coupon'),
    path('coupons/generate-for-user/<int:user_id>/', views.generate_coupon_for_user, name='generate_coupon_for_user'),
    
    # Wallet Management URLs
    path('wallet/history/', views.wallet_history, name='wallet_history'),
    path('wallet/transaction/<int:transaction_id>/update/', views.update_wallet_transaction, name='update_wallet_transaction'),
    path('wallet/export/', views.export_wallet_transactions, name='export_wallet_transactions'),
    
    # Transaction History URL
    path('transactions/', views.admin_transaction_history_view, name='admin_transaction_history'),
]