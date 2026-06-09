import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0012_transactionlogs_discrepancy_items'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='sync_uuid',
            field=models.UUIDField(
                default=uuid.uuid4,
                unique=True,
                db_index=True,
                help_text='Cross-instance unique identifier used for desktop\u2194server data sync.',
            ),
        ),
    ]
