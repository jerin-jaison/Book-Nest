from django.db import migrations, models
import uuid

def generate_order_ids(apps, schema_editor):
    Order = apps.get_model('cart_section', 'Order')
    for order in Order.objects.filter(order_id__isnull=True):
        while True:
            order_id = str(uuid.uuid4().hex)[:10].upper()
            if not Order.objects.filter(order_id=order_id).exists():
                order.order_id = order_id
                order.save()
                break

class Migration(migrations.Migration):
    dependencies = [
        ('cart_section', '0003_remove_order_items_order_cancel_reason_and_more'),
    ]

    operations = [
        # First, run the function to generate order IDs for existing orders
        migrations.RunPython(generate_order_ids),
        
        # Then, alter the field to be non-nullable
        migrations.AlterField(
            model_name='order',
            name='order_id',
            field=models.CharField(max_length=10, unique=True, editable=False),
        ),
    ] 