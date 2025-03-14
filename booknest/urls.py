"""
URL configuration for booknest project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls import handler404
from user_authentication.views import custom_404_view
handler404 = custom_404_view


urlpatterns = [
    path('', include('user_authentication.urls')),
    path('admin_side/', include('admin_side.urls')),
    path('user_profile/', include('user_profile.urls', namespace='user_profile')),
    path('cart_section/', include('cart_section.urls')),
    path('wallet/', include('user_wallet.urls')),
    path('payment/', include('online_payment.urls')),
    path('social-auth/', include('social_django.urls', namespace='social')),
]

# Add media files handling during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
