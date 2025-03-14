from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, models
from django.http import JsonResponse
from django.utils import timezone
from .models import Wallet, WalletTransaction
from cart_section.models import Order
from decimal import Decimal
from django.contrib.auth.models import User

# Create your views here.

def add_referral_reward(user, amount, order_id):
    """
    Add referral reward to user's wallet
    
    Args:
        user: The user who referred the customer
        amount: The amount to add to the wallet
        order_id: The order ID for reference
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with transaction.atomic():
            # Get or create wallet for the user
            wallet, created = Wallet.objects.get_or_create(user=user)
            
            # Create wallet transaction
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type='CREDIT',
                status='COMPLETED',
                description=f'Referral reward for order #{order_id}',
                reference_id=order_id
            )
            
            # Update wallet balance
            wallet.balance += amount
            wallet.save()
            
            return True
    except Exception as e:
        print(f"Error adding referral reward: {str(e)}")
        return False

def deduct_referral_reward(user, amount, order_id, reason):
    """
    Deduct referral reward from user's wallet when a referred order is cancelled or returned
    
    Args:
        user: The user who received the referral reward
        amount: The amount to deduct from the wallet
        order_id: The order ID for reference
        reason: The reason for deduction (e.g., 'cancelled', 'returned')
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with transaction.atomic():
            # Get wallet for the user
            wallet = Wallet.objects.get(user=user)
            
            # Check if user has sufficient balance
            if wallet.balance < amount:
                # If not enough balance, deduct whatever is available
                deduction_amount = wallet.balance
                wallet.balance = Decimal('0.00')
            else:
                # Deduct the full amount
                deduction_amount = amount
                wallet.balance -= amount
            
            # Create wallet transaction
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=deduction_amount,
                transaction_type='DEBIT',
                status='COMPLETED',
                description=f'Referral reward deducted for {reason} order #{order_id}',
                reference_id=order_id
            )
            
            # Save wallet
            wallet.save()
            
            return True
    except Wallet.DoesNotExist:
        print(f"Wallet does not exist for user {user.username}")
        return False
    except Exception as e:
        print(f"Error deducting referral reward: {str(e)}")
        return False

@login_required(login_url='login_page')
def wallet_dashboard(request):
    # Get or create wallet for the user
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    
    # Get recent transactions
    transactions = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')[:10]
    
    # Calculate statistics
    total_credits = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='CREDIT',
        status='COMPLETED'
    ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
    
    total_debits = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='DEBIT',
        status='COMPLETED'
    ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
        'total_credits': total_credits,
        'total_debits': total_debits,
    }
    return render(request, 'user_wallet/wallet_dashboard.html', context)

@login_required(login_url='login_page')
def transaction_history(request):
    wallet = get_object_or_404(Wallet, user=request.user)
    transactions = WalletTransaction.objects.filter(wallet=wallet)
    
    context = {
        'wallet': wallet,
        'transactions': transactions,
    }
    return render(request, 'user_wallet/transaction_history.html', context)

@login_required(login_url='login_page')
def use_wallet_balance(request):
    """
    API endpoint to use wallet balance during checkout
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})
    
    try:
        amount = Decimal(request.POST.get('amount', '0'))
        order_id = request.POST.get('order_id')
        
        if not amount or not order_id:
            return JsonResponse({'status': 'error', 'message': 'Invalid amount or order ID'})
        
        wallet = get_object_or_404(Wallet, user=request.user)
        
        if wallet.balance < amount:
            return JsonResponse({
                'status': 'error',
                'message': 'Insufficient wallet balance'
            })
        
        with transaction.atomic():
            # Create wallet transaction
            wallet_transaction = WalletTransaction.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type='DEBIT',
                status='COMPLETED',
                description=f'Payment for order #{order_id}',
                reference_id=order_id
            )
            
            # Update wallet balance
            wallet.balance -= amount
            wallet.save()
            
            # Update order payment details if needed
            order = Order.objects.get(order_id=order_id)
            order.payment_method = 'WALLET'
            order.save()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Payment successful',
            'new_balance': str(wallet.balance),
            'transaction_id': wallet_transaction.id
        })
        
    except (ValueError, Order.DoesNotExist) as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': 'An error occurred during payment'})
