from django.core.management.base import BaseCommand
from cart_section.models import Order
import uuid

class Command(BaseCommand):
    help = 'Fix orders with missing order_ids'

    def handle(self, *args, **options):
        orders = Order.objects.filter(order_id__isnull=True)
        count = orders.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No orders found with missing order_ids'))
            return
        
        for order in orders:
            # Generate a unique order ID
            while True:
                order_id = str(uuid.uuid4().hex)[:10].upper()
                if not Order.objects.filter(order_id=order_id).exists():
                    break
            
            order.order_id = order_id
            order.save()
        
        self.stdout.write(self.style.SUCCESS(f'Successfully fixed {count} orders')) 