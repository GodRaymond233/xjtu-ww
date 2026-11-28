"""Anonymous startup statistics for the stable portable distribution."""
import datetime
import json
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

from src.portable_update import STABLE_VERSION, _safe_path, _version_parts, installed_version

TELEMETRY_OPTION = 'Anonymous Usage Statistics'
TELEMETRY_ENDPOINT = 'https://ww-stats.godraymond.com/v1/ping'
RECEIPT = 'configs/.last-in-app-update.json'
_lock = threading.Lock()


def _read(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError('Invalid configuration.')
    return data


def _write(path, data):
    path.parent.mkdir(exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_update_receipt(root, journal):
    _write(_safe_path(root, RECEIPT), {'from_version': journal['from_version'], 'to_version': journal['version'],
                                      'journal_id': journal['id']})


def has_prior_configs(root):
    try:
        return any(p.name not in ('telemetry.json', '.last-in-app-update.json') and p.is_file()
                   for p in _safe_path(root, 'configs').glob('*.json'))
    except (ValueError, OSError):
        return False


def _uuid4(value):
    try:
        ident = uuid.UUID(value)
        return ident.version == 4 and str(ident) == value
    except (TypeError, ValueError, AttributeError):
        return False


def _send(endpoint, payload):
    req = Request(endpoint, data=json.dumps(payload).encode('utf-8'),
                  headers={'Content-Type': 'application/json', 'User-Agent': 'XJTU-WW'})
    with urlopen(req, timeout=3) as response:
        return 200 <= response.status < 300


def report_startup_telemetry(root, version, prior_configs, *, now=None):
    forced = os.environ.get('XJTU_WW_TELEMETRY_FORCE') == '1'
    if (os.environ.get('XJTU_WW_TELEMETRY_DISABLED', '').lower() in ('1', 'true', 'yes', 'on')
            or not (forced or getattr(sys, 'frozen', False)) or not STABLE_VERSION.fullmatch(version or '')):
        return False
    endpoint = os.environ.get('XJTU_WW_TELEMETRY_URL', TELEMETRY_ENDPOINT)
    if not endpoint.startswith('https://'):
        return False
    try:
        if not forced and installed_version(root) != version:
            return False
        with _lock:
            prefs = _safe_path(root, 'configs/Basic Options.json')
            if _read(prefs).get(TELEMETRY_OPTION, True) is not True:
                return False
            path = _safe_path(root, 'configs/telemetry.json')
            try:
                state = _read(path)
            except ValueError:
                state = {}
            if not _uuid4(state.get('cid')):
                state = {'cid': str(uuid.uuid4()), 'legacy': bool(prior_configs)}
                _write(path, state)
            zone = datetime.timezone(datetime.timedelta(hours=8))
            today = (now or datetime.datetime.now(zone)).astimezone(zone).date().isoformat()
            prev = state.get('last_version', '')
            receipt_path = _safe_path(root, RECEIPT)
            receipt = _read(receipt_path)
            if not prev:
                event, via = 'install', 'legacy_migration' if state['legacy'] else 'new_install'
            elif prev != version:
                event = 'upgrade'
                if _version_parts(version) < _version_parts(prev):
                    via = 'rollback'
                elif (receipt.get('to_version') == version and receipt.get('journal_id')
                      and receipt['journal_id'] != state.get('last_receipt')
                      and STABLE_VERSION.fullmatch(receipt.get('from_version', ''))):
                    via, prev = 'in_app_update', receipt['from_version']
                else:
                    via = 'manual_upgrade'
            elif state.get('last_active_date') != today:
                event, via = 'active', 'none'
            else:
                return False
            os_label = 'unknown'
            if sys.platform == 'win32':
                build = sys.getwindowsversion().build
                os_label = 'win11' if build >= 22000 else ('win10' if build >= 10240 else 'win')
            payload = {'cid': state['cid'], 'event': event, 'ver': version[1:], 'upgrade_via': via,
                       'prev_ver': prev[1:] if event == 'upgrade' else '', 'os': os_label}
            if not _send(endpoint, payload):
                return False
            state.update(last_version=version, last_active_date=today, last_receipt=receipt.get('journal_id', ''))
            _write(path, state)
            if receipt and _read(receipt_path) == receipt:
                receipt_path.unlink(missing_ok=True)
            return True
    except Exception:
        # A stats or settings failure must never affect startup or a completed update.
        return False
