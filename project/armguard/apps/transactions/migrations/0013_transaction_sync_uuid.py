import uuid
from django.db import migrations, models


def _populate_sync_uuid(apps, schema_editor):
    """Assign a unique UUID to every existing Transaction row.

    SQLite's _remake_table evaluates a callable default ONCE and uses the same
    value for all existing rows, which immediately violates the UNIQUE constraint.
    Running this via RunPython calls uuid.uuid4() individually per row.
    """
    Transaction = apps.get_model('transactions', 'Transaction')
    for txn in Transaction.objects.filter(sync_uuid__isnull=True).iterator():
        txn.sync_uuid = uuid.uuid4()
        txn.save(update_fields=['sync_uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0012_transactionlogs_discrepancy_items'),
    ]

    operations = [
        # Step 1: add the column nullable with no unique constraint so existing
        # rows can be populated one-by-one without a UNIQUE violation.
        migrations.AddField(
            model_name='transaction',
            name='sync_uuid',
            field=models.UUIDField(
                null=True,
                blank=True,
                db_index=True,
                help_text='Cross-instance unique identifier used for desktop\u2194server data sync.',
            ),
        ),
        # Step 2: populate all existing rows with individual unique UUIDs.
        migrations.RunPython(_populate_sync_uuid, migrations.RunPython.noop),
        # Step 3: tighten to NOT NULL + UNIQUE now that every row has a value.
        migrations.AlterField(
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
