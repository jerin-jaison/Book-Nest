from django.urls import path,include
from . import views

urlpatterns = [
    path('', views.home_view, name='home_page'),
    path('login/', views.login_view, name='login_page'),
    path('signup/', views.signup_view, name = 'signup_page' ),
    path('signout/', views.signout_view, name = 'signout' ),
    path('forgetPassword/', views.forgetPassword_view, name='forgetPassword_page'),
    path('otpSignup/', views.otpSignup_view, name='otp_page'),#Forget Password
    path('otpLogin/', views.otpLogin_view, name='otp_page_login'),
    path('reEnterPassword', views.reEnterPassword_view, name='reEnterPassword_page'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),
    path('product_page/', views.product_view, name = 'product_page'),
    path('product/<slug:slug>/', views.product_detail_view, name='product_detail'),

        # Google Authentication URLs
    path('google/login/', views.google_login, name='google_login'),
    path('social-auth/', include('social_django.urls', namespace='social')),
    # path('google/callback/', views.google_callback, name='google_callback'),



]
#HardPass123