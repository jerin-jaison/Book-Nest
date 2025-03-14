from django.urls import path
from . import views

app_name = 'online_payment'

urlpatterns = [
    path('initiate/<str:order_id>/', views.initiate_payment, name='initiate_payment'),
    path('callback/', views.payment_callback, name='payment_callback'),
    path('success/<str:order_id>/', views.payment_success, name='payment_success'),
    path('failure/', views.payment_failure, name='payment_failure'),
]

