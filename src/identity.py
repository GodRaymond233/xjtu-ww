"""Runtime identity layer.

This build rebrands process identity, logs, single-instance markers, window
classes and notifications. Custom scripts keep the framework's canonical
directories so discovery, template editing and packaging share one location.
"""

import logging

APP_SLUG = 'xjtuww'
APP_TITLE = 'XJTU-WW'
PROCESS_TAG = 'xjtu-ww'

# Win32 named objects (the object namespace adds the Global\ prefix).
MUTEX_PREFIX = 'xjtu-ww-singleton.'
OVERLAY_WINDOW_CLASS = 'xjtu.Overlay'
NOTIFIER_APP_USER_MODEL_ID = 'xjtu.ww.shell'
LOG_BASENAME = 'xjtu-ww'

# Keep the framework's canonical paths for discovery, editing and packaging.
SCRIPTS_FOLDER = 'ok_tasks'
IMPORT_FOLDER = 'ok_import'

_UPSTREAM_TOKENS = (
    'ok-wuthering-waves',
    'ok-ww',
    'ok_ww',
    'okww',
    'ok-script',
    'ok_script',
    'okwutheringwaves',
    'ok-oldking',
)


def sanitize_text(value):
    """Rewrite upstream branding inside any runtime string."""
    if not isinstance(value, str):
        return value
    lowered = value.lower()
    if not any(token in lowered for token in _UPSTREAM_TOKENS):
        return value
    result = value
    # Longest tokens first so 'ok-wuthering-waves' wins over its substrings.
    for token in sorted(_UPSTREAM_TOKENS, key=len, reverse=True):
        result = result.replace(token, APP_SLUG)
        result = result.replace(token.upper(), APP_SLUG.upper())
        snake = token.replace('-', '_')
        result = result.replace(snake, APP_SLUG.replace('-', '_'))
        result = result.replace(snake.upper(), APP_SLUG.replace('-', '_').upper())
    return result


class _SanitizingFilter(logging.Filter):
    """Scrub upstream names from log records before any handler sees them."""

    def filter(self, record):
        message = record.getMessage()
        sanitized = sanitize_text(message)
        if sanitized != message:
            record.msg = sanitized
            record.args = None
        if record.exc_text and sanitize_text(record.exc_text) != record.exc_text:
            record.exc_text = sanitize_text(record.exc_text)
        return True


def _patch_logging():
    for logger_name in ('ok', '', 'pyappify'):
        target = logging.getLogger(logger_name)
        if not any(isinstance(item, _SanitizingFilter) for item in target.filters):
            target.addFilter(_SanitizingFilter())


def _patch_logger_file():
    from ok.util import logger as ok_logger_module
    original_config_logger = ok_logger_module.config_logger

    def config_logger(config=None, name=LOG_BASENAME, _original=original_config_logger):
        return _original(config, name)

    ok_logger_module.config_logger = config_logger
    return config_logger


def _patch_mutex():
    """Redirect the single-instance marker to our own %TEMP% filename."""
    from ok.util import process as ok_process

    original_check_mutex = ok_process.check_mutex

    def check_mutex(wait_time=5, kill_wait_time=3, gui=False, _original=original_check_mutex):
        return _redirect_owner_files(lambda: _original(wait_time, kill_wait_time, gui))

    ok_process.check_mutex = check_mutex
    return check_mutex


def _redirect_owner_files(body):
    """While ``body`` runs, rewrite upstream's owner-file writes to our name.

    Upstream builds the marker as ``os.path.join(gettempdir(),
    f'ok-script-{digest}.pid')``. Temporarily wrapping the two stdlib
    functions inside the ``ok.util.process`` module namespace is surgical:
    only that module's globals are affected, and the redirect only fires for
    the exact upstream marker pattern.
    """
    import os
    import tempfile

    process_module = __import__('ok.util.process', fromlist=['os'])
    path_separator = os.sep

    real_join = os.path.join
    real_gettempdir = tempfile.gettempdir
    active = True

    def join(*parts):
        joined = real_join(*parts)
        if active:
            head, _, tail = joined.rpartition(path_separator)
            if tail.startswith('ok-script-') and tail.endswith('.pid'):
                joined = real_join(head, MUTEX_PREFIX + tail[len('ok-script-'):])
        return joined

    def gettempdir():
        return real_gettempdir()

    process_module.os.path.join = join
    process_module.tempfile.gettempdir = gettempdir
    try:
        return body()
    finally:
        active = False
        process_module.os.path.join = real_join
        process_module.tempfile.gettempdir = real_gettempdir


def _patch_window_classes():
    from ok.ui.overlay import win32_gdi
    win32_gdi._window_class_name = OVERLAY_WINDOW_CLASS


class _BoundWrapper:
    """Descriptor adapter.

    Cython compiles module functions to non-descriptor builtins, so wrappers
    assigned to class attributes (``__init__``, methods) never receive
    ``self``. This descriptor restores normal method binding for them.
    """

    __slots__ = ('_fn',)

    def __init__(self, fn):
        self._fn = fn

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self._fn

        def bound(*args, **kwargs):
            return self._fn(obj, *args, **kwargs)

        return bound


def _patch_notifications():
    """Rebrand the system notifier: AUMID, tray window class, balloon text."""
    from ok.notification import system as notifier_module

    original_init = notifier_module.WindowsSystemNotifier.__init__
    original_show = notifier_module.WindowsSystemNotifier.show

    def __init__(self, *args, _original=original_init, **kwargs):
        app_icon = kwargs.get('app_icon') or (args[1] if len(args) > 1 else None)
        _original(self, APP_TITLE, app_icon)
        self.app_id = NOTIFIER_APP_USER_MODEL_ID

    def show(self, title, message, error=False, _original=original_show):
        return _original(self, sanitize_text(title), sanitize_text(message), error)

    notifier_module.WindowsSystemNotifier.__init__ = _BoundWrapper(__init__)
    notifier_module.WindowsSystemNotifier.show = _BoundWrapper(show)


def _patch_log_page():
    """Point the Log page at our log file and its placeholder text."""
    from pathlib import Path
    from ok.ui.qt.shell import log_page as log_page_module

    original_init = log_page_module.LogPage.__init__

    def __init__(self, log_file=None, parent=None, _original=original_init):
        default = Path.cwd() / "logs" / f"{LOG_BASENAME}.log"
        _original(self, log_file or default, parent)

    log_page_module.LogPage.__init__ = _BoundWrapper(__init__)

    original_t = log_page_module._t

    def _t(text, _original=original_t):
        return _original(sanitize_text(text))

    log_page_module._t = _t


def _migrate_script_folders():
    """Move the previous distribution's folders without overwriting user files."""
    from pathlib import Path

    pairs = [(Path('xjtu_scripts'), Path(SCRIPTS_FOLDER)),
             (Path('xjtu_import'), Path(IMPORT_FOLDER))]
    # Preflight both trees before moving anything; a conflict needs user resolution.
    for old, new in pairs:
        if old.exists():
            _check_folder_merge(old, new)
    for old, new in pairs:
        if old.exists():
            _merge_script_folder(old, new)


def _check_folder_merge(source, destination):
    import filecmp
    import os

    if not destination.exists() and not destination.is_symlink():
        return
    if source.is_symlink() or destination.is_symlink():
        same = (source.is_symlink() and destination.is_symlink()
                and os.readlink(source) == os.readlink(destination))
    elif source.is_dir() and destination.is_dir():
        for child in source.iterdir():
            _check_folder_merge(child, destination / child.name)
        return
    else:
        same = (source.is_file() and destination.is_file()
                and filecmp.cmp(source, destination, shallow=False))
    if not same:
        raise FileExistsError(f'Cannot migrate scripts: conflicting files {source} and {destination}')


def _merge_script_folder(source, destination):
    if not destination.exists() and not destination.is_symlink():
        source.rename(destination)
    elif source.is_dir() and not source.is_symlink():
        for child in source.iterdir():
            _merge_script_folder(child, destination / child.name)
        source.rmdir()
    else:
        # Preflight established that this entry is identical to the destination.
        source.unlink()


def _export_ok_globals():
    """The OK class resolves framework symbols through package globals."""
    import ok as ok_package
    from ok.util import logger as ok_logger_module
    from ok.util import process as ok_process

    ok_package.config_logger = ok_logger_module.config_logger
    ok_package.check_mutex = ok_process.check_mutex


def apply():
    """Apply every runtime identity patch. Idempotent, safe to call twice."""
    import ok as ok_package
    if getattr(ok_package, '_xjtu_identity_applied', False):
        return False
    _migrate_script_folders()
    ok_package._xjtu_identity_applied = True

    _patch_logging()
    _patch_logger_file()
    _patch_mutex()
    _patch_window_classes()
    _patch_notifications()
    _patch_log_page()
    _export_ok_globals()
    return True
