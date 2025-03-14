from django.core.management.base import BaseCommand
from django.db.models import Count
from cart_section.models import Order
from django.utils import timezone

class Command(BaseCommand):
    help = 'Cleans up invalid orders (orders with 0 items) from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        # Get orders with no items
        invalid_orders = Order.objects.annotate(
            items_count=Count('items')
        ).filter(items_count=0)

        count = invalid_orders.count()
        
        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(
                    f'Found {count} invalid orders that would be deleted:'
                )
            )
            for order in invalid_orders:
                self.stdout.write(
                    self.style.WARNING(
                        f'Order #{order.order_id} - Created: {order.created_at}, '
                        f'User: {order.user.email if order.user else "No user"}'
                    )
                )
        else:
            # Actually delete the orders
            deletion_details = invalid_orders.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully deleted {count} invalid orders'
                )
            )
            
            # Log the cleanup action
            with open('order_cleanup_log.txt', 'a') as f:
                f.write(f'\nCleanup performed at {timezone.now()}\n')
                f.write(f'Deleted {count} invalid orders\n')
                f.write('-' * 50 + '\n') 