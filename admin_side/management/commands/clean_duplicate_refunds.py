from django.core.management.base import BaseCommand
from django.db import transaction
from cart_section.models import Order
from user_wallet.models import Wallet, WalletTransaction
from decimal import Decimal

class Command(BaseCommand):
    help = 'Clean up duplicate refund transactions for all orders'
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting cleanup of duplicate refund transactions...'))
        
        # Get all orders with RETURNED status and REFUNDED payment status
        orders = Order.objects.filter(status='RETURNED', payment_status='REFUNDED')
        self.stdout.write(f'Found {orders.count()} returned orders with refunded payment status')
        
        total_pending_cleaned = 0
        total_duplicates_cleaned = 0
        total_amount_deducted = Decimal('0.00')
        
        for order in orders:
            try:
                with transaction.atomic():
                    # Get the user's wallet
                    try:
                        wallet = Wallet.objects.get(user=order.user)
                    except Wallet.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f'No wallet found for user {order.user.username} (Order #{order.order_id})'))
                        continue
                    
                    # Clean up pending transactions
                    pending_transactions = WalletTransaction.objects.filter(
                        wallet=wallet,
                        reference_id=order.order_id,
                        transaction_type='CREDIT',
                        status='PENDING',
                        description__contains='Refund for'
                    )
                    
                    pending_count = pending_transactions.count()
                    if pending_count > 0:
                        pending_transactions.delete()
                        total_pending_cleaned += pending_count
                        self.stdout.write(self.style.SUCCESS(f'Cleaned {pending_count} pending transactions for Order #{order.order_id}'))
                    
                    # Find all completed refund transactions for this order
                    completed_transactions = WalletTransaction.objects.filter(
                        wallet=wallet,
                        reference_id=order.order_id,
                        transaction_type='CREDIT',
                        status='COMPLETED',
                        description__contains='Refund for'
                    ).order_by('created_at')
                    
                    # If there's more than one transaction, keep the first one and delete the rest
                    if completed_transactions.count() > 1:
                        # Get the first (oldest) transaction
                        first_transaction = completed_transactions.first()
                        
                        # Delete all other transactions
                        duplicates = completed_transactions.exclude(id=first_transaction.id)
                        duplicate_count = duplicates.count()
                        
                        # Calculate the total amount to deduct from the wallet
                        duplicate_amount = sum(t.amount for t in duplicates)
                        
                        # Deduct the duplicate amounts from the wallet
                        if duplicate_amount > 0:
                            wallet.balance -= duplicate_amount
                            wallet.save()
                            total_amount_deducted += duplicate_amount
                        
                        # Delete the duplicates
                        duplicates.delete()
                        
                        total_duplicates_cleaned += duplicate_count
                        self.stdout.write(self.style.SUCCESS(
                            f'Cleaned {duplicate_count} duplicate transactions for Order #{order.order_id}. '
                            f'Deducted ₹{duplicate_amount} from wallet.'
                        ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error processing Order #{order.order_id}: {str(e)}'))
        
        self.stdout.write(self.style.SUCCESS(
            f'Cleanup completed. Removed {total_pending_cleaned} pending and {total_duplicates_cleaned} duplicate transactions. '
            f'Total amount deducted from wallets: ₹{total_amount_deducted}'
        )) 