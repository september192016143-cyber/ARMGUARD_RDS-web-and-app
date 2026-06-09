"""
ARMGUARD Sync API Views

Two endpoints that the desktop sync client calls:

  GET  /api/v1/sync/pull/?since=<ISO-8601>
       Returns all records changed after `since` for:
       personnel, pistol, rifle, magazine, ammunition, accessory, transaction, logs

  POST /api/v1/sync/push/
       Desktop sends its local transaction + log records.
       Server upserts by sync_uuid (idempotent — safe to call multiple times).

Authentication: DRF Token auth (IsAdminUser required).
The token is created once on the server with:
    python manage.py drf_create_token <username>
and stored in the desktop's .env as SYNC_API_TOKEN.
"""
import logging
from datetime import datetime, timezone as dt_tz

from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from armguard.apps.inventory.models import Pistol, Rifle, Magazine, Ammunition, Accessory
from armguard.apps.personnel.models import Personnel
from armguard.apps.transactions.models import Transaction, TransactionLogs

from .sync_serializers import (
    _LOG_TXN_FK_FIELDS,
    SyncPersonnelSerializer,
    SyncPistolSerializer, SyncRifleSerializer,
    SyncMagazineSerializer, SyncAmmunitionSerializer, SyncAccessorySerializer,
    SyncTransactionSerializer, SyncTransactionLogsSerializer,
)

logger = logging.getLogger('armguard.sync')

_EPOCH = datetime(1970, 1, 1, tzinfo=dt_tz.utc)


def _parse_since(request) -> datetime:
    """Parse the ?since= query parameter.  Returns epoch if absent or invalid."""
    raw = request.query_params.get('since', '')
    if raw:
        dt = parse_datetime(raw)
        if dt:
            # Make timezone-aware if naive.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_tz.utc)
            return dt
    return _EPOCH


class SyncPullView(APIView):
    """
    GET /api/v1/sync/pull/?since=<ISO-8601>

    Returns a JSON snapshot of all records that changed after `since`.
    The desktop client calls this to populate its local database on first run
    and to detect incremental changes on subsequent runs.

    For inventory and personnel (which lack reliable auto_now updated_at fields),
    ALL records are returned regardless of `since`. This ensures the desktop
    always has a complete, accurate picture of server-side reference data.

    For transactions and logs (which have updated_at / timestamp), only records
    newer than `since` are returned.
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        since = _parse_since(request)

        # Reference data — always send full list (server is authoritative).
        personnel   = Personnel.objects.all()
        pistols     = Pistol.objects.all()
        rifles      = Rifle.objects.all()
        magazines   = Magazine.objects.all()
        ammunition  = Ammunition.objects.all()
        accessories = Accessory.objects.all()

        # Operational data — only changes since `since`.
        transactions = Transaction.objects.filter(updated_at__gte=since).order_by('timestamp')
        # TransactionLogs has 20 separate FK columns to Transaction; there is no
        # single 'transaction' FK field.  Build an OR filter across all FK columns
        # to find logs associated with the transactions we're returning.
        txn_pks = list(transactions.values_list('transaction_id', flat=True))
        if txn_pks:
            _log_q = Q()
            for _fk in _LOG_TXN_FK_FIELDS:
                _log_q |= Q(**{f'{_fk}__in': txn_pks})
            # select_related on all 20 relation descriptors (without '_id') so the
            # serializer's get__transaction_sync_uuids does not trigger N+1 queries.
            _log_rel_names = [f[:-3] for f in _LOG_TXN_FK_FIELDS]
            logs = (TransactionLogs.objects
                    .filter(_log_q)
                    .distinct()
                    .select_related(*_log_rel_names)
                    .order_by('record_id'))
        else:
            logs = TransactionLogs.objects.none()

        payload = {
            'personnel':    SyncPersonnelSerializer(personnel,   many=True).data,
            'pistols':      SyncPistolSerializer(pistols,         many=True).data,
            'rifles':       SyncRifleSerializer(rifles,           many=True).data,
            'magazines':    SyncMagazineSerializer(magazines,     many=True).data,
            'ammunition':   SyncAmmunitionSerializer(ammunition,  many=True).data,
            'accessories':  SyncAccessorySerializer(accessories,  many=True).data,
            'transactions': SyncTransactionSerializer(transactions, many=True).data,
            'logs':         SyncTransactionLogsSerializer(logs,   many=True).data,
        }
        return Response(payload)


class SyncPushView(APIView):
    """
    POST /api/v1/sync/push/

    Accepts a JSON body from the desktop with transactions and logs created
    locally that the server does not yet have.

    Body schema:
        {
          "transactions": [ <Transaction fields> ... ],
          "logs":         [ <TransactionLogs fields> ... ]
        }

    Each transaction is upserted by sync_uuid — duplicate pushes are safe.
    The server stores the records as raw data (bypassing Transaction.save()
    business logic) to avoid re-running side effects that already ran on the
    desktop.  Inventory/personnel status changes are authoritative on the
    server; the desktop pulls those back via the pull endpoint.

    Returns:
        { "created": N, "updated": N, "errors": [ ... ] }
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        data = request.data
        if not isinstance(data, dict):
            return Response({'detail': 'Expected a JSON object.'}, status=status.HTTP_400_BAD_REQUEST)

        created_count = 0
        updated_count = 0
        errors = []

        txn_records = data.get('transactions', [])
        log_records = data.get('logs', [])

        # ── Transactions ──────────────────────────────────────────────────────
        # Each record runs in its own atomic() block so an IntegrityError on
        # one row does not leave the connection in an error state and does not
        # roll back records that have already succeeded.
        for rec in txn_records:
            sync_uuid = rec.get('sync_uuid')
            if not sync_uuid:
                errors.append({'record': rec, 'error': 'sync_uuid is required'})
                continue

            # Remove auto-set or server-side-only fields from the incoming record.
            rec.pop('updated_at', None)

            try:
                with db_transaction.atomic():
                    existing = Transaction.objects.filter(sync_uuid=sync_uuid).first()
                    if existing is None:
                        # Use bulk_create to bypass Transaction.save() side effects.
                        # Those side effects (inventory status updates, TransactionLogs
                        # creation, consumable adjustments) already ran on the desktop
                        # that originated this transaction.  Re-running them here would
                        # produce duplicate logs and double inventory adjustments.
                        defaults = _build_transaction_defaults(rec)
                        obj = Transaction(**defaults)
                        obj.sync_uuid = sync_uuid
                        Transaction.objects.bulk_create([obj], ignore_conflicts=True)
                        created_count += 1
                        logger.info('Sync: created transaction sync_uuid=%s', sync_uuid)
                    else:
                        # Transaction already exists — update safe mutable fields only.
                        _apply_transaction_updates(existing, rec)
                        updated_count += 1
                        logger.info('Sync: updated transaction sync_uuid=%s', sync_uuid)
            except Exception as exc:
                logger.warning('Sync push error for transaction sync_uuid=%s: %s', sync_uuid, exc)
                errors.append({'sync_uuid': str(sync_uuid), 'error': str(exc)})

        # ── TransactionLogs ───────────────────────────────────────────────────
        for rec in log_records:
            record_id = rec.get('record_id')
            if not record_id:
                continue
            try:
                with db_transaction.atomic():
                    # Build defaults, skipping the PK and the helper field.
                    defaults = {
                        k: v for k, v in rec.items()
                        if k not in ('record_id', '_transaction_sync_uuids')
                        and k not in _LOG_TXN_FK_FIELDS
                        and v is not None
                    }
                    # Resolve each Transaction FK via its sync_uuid.
                    uuid_map = rec.get('_transaction_sync_uuids') or {}
                    for fk_field, sync_uuid_str in uuid_map.items():
                        if not sync_uuid_str:
                            continue
                        try:
                            txn = Transaction.objects.get(sync_uuid=sync_uuid_str)
                            # fk_field already ends with '_id' (e.g. 'withdrawal_pistol_transaction_id')
                            # so assign directly — do NOT add another '_id' suffix.
                            defaults[fk_field] = txn.transaction_id
                        except Transaction.DoesNotExist:
                            pass
                    TransactionLogs.objects.get_or_create(
                        record_id=record_id,
                        defaults=defaults,
                    )
            except Exception as exc:
                logger.warning('Sync push error for log record_id=%s: %s', record_id, exc)
                errors.append({'record_id': record_id, 'error': str(exc)})

        result = {'created': created_count, 'updated': updated_count}
        if errors:
            result['errors'] = errors
        return Response(result, status=status.HTTP_200_OK)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_transaction_defaults(rec: dict) -> dict:
    """Build the `defaults` dict for Transaction.objects.get_or_create().

    Resolves FK fields (personnel, pistol, rifle, etc.) from their PK values
    in the incoming record, falling back gracefully when the FK target is absent.
    """
    defaults = {}
    fk_map = {
        'personnel':           ('personnel', Personnel,   'Personnel_ID'),
        'pistol':              ('pistol',    Pistol,      'item_id'),
        'rifle':               ('rifle',     Rifle,       'item_id'),
        'pistol_magazine':     ('pistol_magazine', Magazine, 'id'),
        'rifle_magazine':      ('rifle_magazine',  Magazine, 'id'),
        'pistol_ammunition':   ('pistol_ammunition',   Ammunition, 'id'),
        'rifle_ammunition':    ('rifle_ammunition',    Ammunition, 'id'),
        'accessory':           ('accessory', Accessory, 'id'),
    }
    skip = {'transaction_id', 'sync_uuid', 'updated_at'}

    for key, value in rec.items():
        if key in skip or value is None:
            continue
        if key in fk_map:
            field_name, model_cls, pk_field = fk_map[key]
            try:
                defaults[field_name] = model_cls.objects.get(**{pk_field: value})
            except model_cls.DoesNotExist:
                defaults[field_name] = None
        else:
            defaults[key] = value

    return defaults


def _apply_transaction_updates(obj: Transaction, rec: dict) -> None:
    """Update mutable fields on an existing Transaction from the sync record.

    Only updates fields that are safe to change after creation (notes, return_by,
    etc.).  Structural fields (personnel, items) are not overwritten to avoid
    corrupting server-side state.
    """
    mutable = {'notes', 'purpose_other', 'return_by', 'transaction_personnel'}
    changed = False
    for field in mutable:
        if field in rec and getattr(obj, field) != rec[field]:
            setattr(obj, field, rec[field])
            changed = True
    if changed:
        # Use update() to skip Transaction.save() business logic.
        Transaction.objects.filter(pk=obj.pk).update(
            **{f: getattr(obj, f) for f in mutable if hasattr(obj, f)}
        )
