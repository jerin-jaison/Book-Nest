from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('cart_section', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='status',
            field=models.CharField(
                choices=[
                    ('CONFIRMED', 'Confirmed'),
                    ('SHIPPED', 'Shipped'),
                    ('DELIVERED', 'Delivered'),
                    ('CANCELLED', 'Cancelled'),
                    ('RETURNED', 'Returned'),
                    ('RETURN_REQUESTED', 'Return Requested'),
                    ('RETURN_REJECTED', 'Return Rejected'),
                ],
                default='CONFIRMED',
                max_length=20
            ),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ] 