"""
ARMGUARD Desktop Sync Client

Synchronises the local SQLite database with the central ARMGUARD server.

Data flow:
  PULL (server → desktop):
    - Personnel, Pistol, Rifle, Magazine, Ammunition, Accessory — full table
      replace (server is authoritative for all reference data).
    - Transaction, TransactionLogs — incremental (records changed since last sync).

  PUSH (desktop → server):
    - Transactions and logs that exist locally but whose sync_uuid the server
      has not seen yet.

Configuration (.env):
    SYNC_SERVER_URL        Base URL of the server, e.g. http://10.100.5.52
    SYNC_API_TOKEN         DRF token (create on server with:
                             python manage.py drf_create_token <username>)
    SYNC_INTERVAL_MINUTES  How often the background thread runs (default: 5)
    SYNC_ENABLED           Set to False to disable sync entirely (default: True)

State file:
    .sync_state.json at the repository root stores the timestamp of the last
    successful pull so incremental transaction syncs work correctly.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone as dt_tz
from pathlib import Path
from typing import Any

import django
from django.db import transaction as db_transaction

logger = logging.getLogger('armguard.sync')

ROOT_DIR = Path(__file__).resolve().parent
SYNC_STATE_FILE = ROOT_DIR / '.sync_state.json'

_EPOCH_STR = '1970-01-01T00:00:00Z'


# ── State helpers ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if SYNC_STATE_FILE.exists():
        try:
            return json.loads(SYNC_STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'last_sync': _EPOCH_STR}


def _save_state(state: dict) -> None:
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _make_session(token: str):
    """Return a requests.Session pre-configured with the API token header."""
    import requests  # type: ignore[import-untyped]
    s = requests.Session()
    s.headers.update({
        'Authorization': f'Token {token}',
        'Content-Type':  'application/json',
        'Accept':        'application/json',
    })
    return s


# ── Model upsert helpers ───────────────────────────────────────────────────────

_PERSONNEL_EXCLUDE = frozenset({
    'Personnel_ID',
    'qr_code_image',
    'personnel_image',
    # user is a OneToOneField to AUTH_USER_MODEL; user PKs differ across
    # instances and cannot be reliably synced without a user-mapping table.
    'user',
})


def _upsert_personnel(records: list[dict]) -> tuple[int, int]:
    from armguard.apps.personnel.models import Personnel
    created = updated = 0
    for rec in records:
        pk = rec.get('Personnel_ID')
        if not pk:
            continue
        try:
            _, is_new = Personnel.objects.update_or_create(
                Personnel_ID=pk,
                defaults={
                    k: v for k, v in rec.items()
                    if k not in _PERSONNEL_EXCLUDE and v is not None
                },
            )
            if is_new:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            logger.warning('Sync upsert Personnel %s: %s', pk, exc)
    return created, updated


# FK fields that DRF ModelSerializer serialises as bare PKs under the
# plain field name (e.g. "item_assigned_to": "P001").  Django's ORM
# requires the _id-suffixed name when passing raw PKs to update_or_create.
_FK_RENAME = {
    'item_assigned_to':  'item_assigned_to_id',
    'item_issued_to':    'item_issued_to_id',
    'category':          'category_id',
    'personnel_id':      'personnel_id_id',  # Personnel.PersonnelGroup FK if any
}


def _upsert_model(model_cls, records: list[dict], pk_field: str,
                  exclude_fields: tuple = ()) -> tuple[int, int]:
    """Generic upsert for inventory models."""
    created = updated = 0
    exclude = set(exclude_fields) | {'qr_code_image', 'item_tag', 'serial_image'}
    for rec in records:
        pk = rec.get(pk_field)
        if not pk:
            continue
        defaults = {}
        for k, v in rec.items():
            if k == pk_field or k in exclude:
                continue
            # Remap bare FK names to the _id-suffixed form Django expects.
            orm_key = _FK_RENAME.get(k, k)
            defaults[orm_key] = v
        try:
            _, is_new = model_cls.objects.update_or_create(
                **{pk_field: pk}, defaults=defaults,
            )
            if is_new:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            logger.warning('Sync upsert %s pk=%s: %s', model_cls.__name__, pk, exc)
    return created, updated


def _upsert_transactions(records: list[dict]) -> tuple[int, int]:
    """
    Upsert transactions by sync_uuid.

    Runs UPDATE via QuerySet.update() to skip Transaction.save() side effects
    (inventory status changes, log creation) since those already ran when the
    transaction was originally created on whichever side originated it.
    """
    from armguard.apps.transactions.models import Transaction
    from armguard.apps.personnel.models import Personnel
    from armguard.apps.inventory.models import Pistol, Rifle, Magazine, Ammunition, Accessory

    FK_MAP = {
        'personnel':          (Personnel,   'Personnel_ID'),
        'pistol':             (Pistol,      'item_id'),
        'rifle':              (Rifle,       'item_id'),
        'pistol_magazine':    (Magazine,    'id'),
        'rifle_magazine':     (Magazine,    'id'),
        'pistol_ammunition':  (Ammunition,  'id'),
        'rifle_ammunition':   (Ammunition,  'id'),
        'accessory':          (Accessory,   'id'),
    }
    SKIP = {'transaction_id', 'updated_at', 'par_document'}

    created = updated = 0
    for rec in records:
        sync_uuid = rec.get('sync_uuid')
        if not sync_uuid:
            continue

        # Resolve FK values to model instances.
        resolved: dict[str, Any] = {}
        for key, value in rec.items():
            if key in SKIP or value is None:
                continue
            if key in FK_MAP:
                model_cls, pk_field = FK_MAP[key]
                try:
                    resolved[key] = model_cls.objects.get(**{pk_field: value})
                except model_cls.DoesNotExist:
                    resolved[key] = None
            else:
                resolved[key] = value

        try:
            existing = Transaction.objects.filter(sync_uuid=sync_uuid).first()
            if existing is None:
                # Build a Transaction instance and save it with raw SQL via
                # QuerySet.bulk_create() so Transaction.save() side-effects
                # (inventory status changes, log creation) are NOT re-run —
                # those already happened on the originating side.
                resolved.pop('sync_uuid', None)
                obj = Transaction(**resolved)
                obj.sync_uuid = sync_uuid
                Transaction.objects.bulk_create(
                    [obj],
                    update_conflicts=False,
                    ignore_conflicts=True,
                )
                created += 1
            else:
                # Transaction already exists — only update safe mutable fields.
                mutable = {k: resolved[k] for k in ('notes', 'purpose_other', 'return_by')
                           if k in resolved}
                if mutable:
                    Transaction.objects.filter(sync_uuid=sync_uuid).update(**mutable)
                updated += 1
        except Exception as exc:
            logger.warning('Sync upsert Transaction sync_uuid=%s: %s', sync_uuid, exc)

    return created, updated


# Transaction FK field names present on TransactionLogs.
# Auto-increment PKs differ across instances; resolve via _transaction_sync_uuids.
_LOG_TXN_FK_FIELDS = frozenset([
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
])


def _upsert_logs(records: list[dict]) -> tuple[int, int]:
    """Upsert TransactionLogs records pulled from the server.

    TransactionLogs PK is `record_id` (AutoField).  Each Transaction FK field
    is resolved by its sync_uuid (from the `_transaction_sync_uuids` helper
    field added by SyncTransactionLogsSerializer) so that auto-increment PK
    differences between instances do not corrupt the FK relationships.
    """
    from armguard.apps.transactions.models import TransactionLogs, Transaction
    created = updated = 0
    for rec in records:
        record_id = rec.get('record_id')
        if not record_id:
            continue

        # Build defaults: skip the PK, the helper field, and bare Transaction FK
        # names (handled below via sync_uuid lookup).
        defaults = {
            k: v for k, v in rec.items()
            if k not in ('record_id', '_transaction_sync_uuids')
            and k not in _LOG_TXN_FK_FIELDS
            and v is not None
        }

        # Resolve each Transaction FK from the sync_uuid map.
        uuid_map = rec.get('_transaction_sync_uuids') or {}
        for fk_field, sync_uuid_str in uuid_map.items():
            if not sync_uuid_str:
                continue
            try:
                txn = Transaction.objects.get(sync_uuid=sync_uuid_str)
                # Use _id suffix to set FK column directly without an extra query.
                defaults[f'{fk_field}_id'] = txn.transaction_id
            except Transaction.DoesNotExist:
                logger.debug(
                    'Sync log: Transaction sync_uuid=%s not found, skipping FK %s',
                    sync_uuid_str, fk_field,
                )

        try:
            _, is_new = TransactionLogs.objects.update_or_create(
                record_id=record_id, defaults=defaults,
            )
            if is_new:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            logger.warning('Sync upsert TransactionLogs record_id=%s: %s', record_id, exc)
    return created, updated


# ── Main sync client ───────────────────────────────────────────────────────────

class SyncClient:
    """Handles all communication with the server sync endpoints."""

    def __init__(self, server_url: str, token: str):
        self.base = server_url.rstrip('/')
        self.token = token

    # ── Pull ──────────────────────────────────────────────────────────────────
    def pull(self, since: str = _EPOCH_STR) -> dict:
        """Pull all changed records from the server since `since` (ISO-8601 string)."""
        import requests
        session = _make_session(self.token)
        url = f'{self.base}/api/v1/sync/pull/?since={since}'
        logger.info('Sync pull: %s', url)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ── Push ──────────────────────────────────────────────────────────────────
    def push(self, transactions: list, logs: list) -> dict:
        """Push local-only transactions and logs to the server."""
        import requests
        if not transactions and not logs:
            return {'created': 0, 'updated': 0}
        session = _make_session(self.token)
        url = f'{self.base}/api/v1/sync/push/'
        payload = {'transactions': transactions, 'logs': logs}
        logger.info('Sync push: %d transactions, %d logs', len(transactions), len(logs))
        resp = session.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    # ── Collect local-only transactions ───────────────────────────────────────
    @staticmethod
    def _local_transactions_to_push(since: str) -> tuple[list, list]:
        """
        Collect transactions and logs that were created/updated after `since`
        so the server gets a copy.
        """
        from armguard.apps.transactions.models import Transaction, TransactionLogs
        from armguard.apps.api.sync_serializers import (
            SyncTransactionSerializer, SyncTransactionLogsSerializer,
        )
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(since)
        if dt and dt.tzinfo is None:
            from datetime import timezone as _tz
            dt = dt.replace(tzinfo=_tz.utc)

        qs = Transaction.objects.filter(updated_at__gte=dt) if dt else Transaction.objects.all()
        txn_data = SyncTransactionSerializer(qs, many=True).data

        log_qs = TransactionLogs.objects.filter(transaction__in=qs)
        log_data = SyncTransactionLogsSerializer(log_qs, many=True).data

        return list(txn_data), list(log_data)

    # ── Full sync cycle ───────────────────────────────────────────────────────
    def sync(self) -> None:
        """Run a full pull-then-push sync cycle."""
        from armguard.apps.inventory.models import Pistol, Rifle, Magazine, Ammunition, Accessory

        state = _load_state()
        last_sync = state.get('last_sync', _EPOCH_STR)

        # ── PULL ──────────────────────────────────────────────────────────────
        logger.info('Starting sync pull (since=%s)', last_sync)
        data = self.pull(since=last_sync)

        with db_transaction.atomic():
            c, u = _upsert_personnel(data.get('personnel', []))
            logger.info('Personnel   created=%d updated=%d', c, u)

            c, u = _upsert_model(Pistol,      data.get('pistols', []),      'item_id')
            logger.info('Pistols     created=%d updated=%d', c, u)

            c, u = _upsert_model(Rifle,       data.get('rifles', []),       'item_id')
            logger.info('Rifles      created=%d updated=%d', c, u)

            c, u = _upsert_model(Magazine,    data.get('magazines', []),    'id')
            logger.info('Magazines   created=%d updated=%d', c, u)

            c, u = _upsert_model(Ammunition,  data.get('ammunition', []),   'id')
            logger.info('Ammunition  created=%d updated=%d', c, u)

            c, u = _upsert_model(Accessory,   data.get('accessories', []),  'id')
            logger.info('Accessories created=%d updated=%d', c, u)

            c, u = _upsert_transactions(data.get('transactions', []))
            logger.info('Transactions created=%d updated=%d', c, u)

            c, u = _upsert_logs(data.get('logs', []))
            logger.info('Logs         created=%d updated=%d', c, u)

        # ── PUSH ──────────────────────────────────────────────────────────────
        txns, logs = self._local_transactions_to_push(last_sync)
        if txns:
            result = self.push(txns, logs)
            errors = result.get('errors', [])
            if errors:
                logger.warning('Sync push errors: %s', errors)
            logger.info(
                'Push result: created=%d updated=%d errors=%d',
                result.get('created', 0), result.get('updated', 0), len(errors),
            )

        # ── Update state ──────────────────────────────────────────────────────
        now_str = datetime.now(tz=dt_tz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        _save_state({'last_sync': now_str})
        logger.info('Sync complete. Next since=%s', now_str)


# ── Background thread entry point ─────────────────────────────────────────────

def run_sync_loop(server_url: str, token: str, interval_minutes: int = 5) -> None:
    """
    Runs sync() every `interval_minutes` minutes in a daemon thread.
    Call this from desktop_app.py after django.setup().
    """
    client = SyncClient(server_url, token)
    interval = interval_minutes * 60

    while True:
        try:
            client.sync()
        except Exception as exc:
            logger.error('Sync cycle failed: %s', exc)
        time.sleep(interval)


def start_sync_thread(server_url: str, token: str, interval_minutes: int = 5) -> threading.Thread:
    """Start and return the background sync daemon thread."""
    t = threading.Thread(
        target=run_sync_loop,
        args=(server_url, token, interval_minutes),
        daemon=True,
        name='armguard-sync',
    )
    t.start()
    logger.info(
        'Sync thread started (server=%s, interval=%dm)', server_url, interval_minutes
    )
    return t
