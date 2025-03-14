from django.urls import path
from . import views

app_name = 'user_wallet'

urlpatterns = [
    path('', views.wallet_dashboard, name='wallet_dashboard'),
    path('transactions/', views.transaction_history, name='transaction_history'),
    path('use-balance/', views.use_wallet_balance, name='use_wallet_balance'),
]

