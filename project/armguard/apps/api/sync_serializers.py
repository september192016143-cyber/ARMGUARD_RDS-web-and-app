"""
ARMGUARD Sync Serializers — full-field serializers for desktop↔server sync.

Unlike the public read-only API serializers (api/serializers.py), these expose
ALL model fields needed to faithfully replicate a record on the other side.

Used by:
  - SyncPullView  (server → desktop)
  - SyncPushView  (desktop → server)
  - desktop sync_client.py
"""
from rest_framework import serializers

from armguard.apps.inventory.models import Pistol, Rifle, Magazine, Ammunition, Accessory
from armguard.apps.personnel.models import Personnel
from armguard.apps.transactions.models import Transaction, TransactionLogs


# ── Personnel ─────────────────────────────────────────────────────────────────
class SyncPersonnelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Personnel
        exclude = [
            # Exclude large binary/media fields — syncing image files is out of scope.
            'qr_code_image',
            'personnel_image',
            # Exclude the user OneToOneField — user PKs differ across instances and
            # trying to set a non-existent FK on the receiving side causes IntegrityError.
            'user',
        ]
        extra_kwargs = {f: {'required': False} for f in ['Personnel_ID']}


# ── Inventory ─────────────────────────────────────────────────────────────────
_EXCLUDE_MEDIA = ['qr_code_image', 'item_tag', 'serial_image']


class SyncPistolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pistol
        exclude = _EXCLUDE_MEDIA


class SyncRifleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rifle
        exclude = _EXCLUDE_MEDIA


class SyncMagazineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Magazine
        fields = '__all__'


class SyncAmmunitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ammunition
        fields = '__all__'


class SyncAccessorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Accessory
        fields = '__all__'


# Transaction FK field names used by both serializer and upsert helpers.
_LOG_TXN_FK_FIELDS = [
    'withdrawal_pistol_transaction_id',
    'withdrawal_rifle_transaction_id',
    'withdrawal_pistol_magazine_transaction_id',
    'withdrawal_rifle_magazine_transaction_id',
    'withdrawal_pistol_ammunition_transaction_id',
    'withdrawal_rifle_ammunition_transaction_id',
    'withdrawal_pistol_holster_transaction_id',
    'withdrawal_magazine_pouch_transaction_id',
    'withdrawal_rifle_sling_transaction_id',
    'withdrawal_bandoleer_transaction_id',
    'return_pistol_transaction_id',
    'return_rifle_transaction_id',
    'return_pistol_magazine_transaction_id',
    'return_rifle_magazine_transaction_id',
    'return_pistol_ammunition_transaction_id',
    'return_rifle_ammunition_transaction_id',
    'return_pistol_holster_transaction_id',
    'return_magazine_pouch_transaction_id',
    'return_rifle_sling_transaction_id',
    'return_bandoleer_transaction_id',
]


# ── Transactions ──────────────────────────────────────────────────────────────
class SyncTransactionSerializer(serializers.ModelSerializer):
    """Full transaction serializer.

    FKs are represented as their PK values (integer / string) so the receiving
    side can link them to the locally-present records.  The par_document file
    is excluded from sync (PDF files are too large for API transfer).
    """
    class Meta:
        model = Transaction
        exclude = ['par_document']


class SyncTransactionLogsSerializer(serializers.ModelSerializer):
    """Full TransactionLogs serializer.

    Adds `_transaction_sync_uuids` — a dict mapping each Transaction FK field
    name to its Transaction.sync_uuid.  The receiving side uses this to resolve
    the correct Transaction row regardless of the auto-increment PK value
    on that instance (PKs differ between server and desktop).
    """
    _transaction_sync_uuids = serializers.SerializerMethodField()

    def get__transaction_sync_uuids(self, obj):
        result = {}
        for field_name in _LOG_TXN_FK_FIELDS:
            # field_name ends with '_id' (e.g. 'withdrawal_pistol_transaction_id').
            # getattr(obj, field_name) returns the raw integer PK column value, not
            # a Transaction instance.  Strip '_id' to use the relation descriptor
            # which returns the actual Transaction object (or None if unset).
            rel_name = field_name[:-3]  # 'withdrawal_pistol_transaction_id' → 'withdrawal_pistol_transaction'
            txn = getattr(obj, rel_name, None)
            if txn is not None:
                try:
                    result[field_name] = str(txn.sync_uuid)
                except Exception:
                    pass
        return result

    class Meta:
        model = TransactionLogs
        fields = '__all__'
