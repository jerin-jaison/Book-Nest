from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse

class BlockedUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if user is authenticated and blocked
        if request.user.is_authenticated and not request.user.is_active:
            # Logout the user
            from django.contrib.auth import logout
            logout(request)
            
            # Add message
            messages.error(request, 'Your account has been blocked by the admin. Please contact support for more information.')
            
            # Redirect to login page
            return redirect('login_page')
            
        response = self.get_response(request)
        return response


class PreventBackButtonMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Add cache control headers to prevent browsers from caching pages for authenticated users
        if request.user.is_authenticated:
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        
        return response 