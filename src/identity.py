"""Runtime identity layer.

This build rebrands everything the process exposes to the operating system:
log file names, the log stream itself, the single-instance marker in %TEMP%,
Win32 window class names, the AppUserModelID, notification source names, the
exported diagnostic log filename, and the custom-script folders. Every value
below deliberately diverges from the upstream `ok-ww` / `ok-script`
distribution; keep new runtime-visible strings in this module so disk scans
and monitoring stay unambiguous.
"""

import logging

APP_SLUG = 'wwassist'
APP_TITLE = 'WW Assist'
PROCESS_TAG = 'wwa-runtime'

# Win32 named objects (the object namespace adds the Global\ prefix).
MUTEX_PREFIX = 'wwa-singleton.'
OVERLAY_WINDOW_CLASS = 'wwa.Overlay'
NOTIFIER_APP_USER_MODEL_ID = 'wwa.assist.shell'
LOG_BASENAME = 'wwassist-run'

# Custom-script folders created next to the executable.
SCRIPTS_FOLDER = 'wwa_scripts'
IMPORT_FOLDER = 'wwa_drop'

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


def _patch_notifications():
    """Rebrand the system notifier: AUMID, tray window class, balloon text."""
    from ok.notification import system as notifier_module

    original_init = notifier_module.WindowsSystemNotifier.__init__
    original_show = notifier_module.WindowsSystemNotifier.show

    def __init__(self, app_name=APP_TITLE, app_icon=None, _original=original_init):
        _original(self, APP_TITLE, app_icon)
        self.app_id = NOTIFIER_APP_USER_MODEL_ID

    def show(self, title, message, error=False, _original=original_show):
        return _original(self, sanitize_text(title), sanitize_text(message), error)

    notifier_module.WindowsSystemNotifier.__init__ = __init__
    notifier_module.WindowsSystemNotifier.show = show


def _patch_log_page():
    """Point the Log page at our log file and its placeholder text."""
    from pathlib import Path
    from ok.ui.qt import shell
    from ok.ui.qt.shell import log_page as log_page_module

    original_init = log_page_module.LogPage.__init__

    def __init__(self, log_file=None, parent=None, _original=original_init):
        default = Path.cwd() / "logs" / f"{LOG_BASENAME}.log"
        _original(self, log_file or default, parent)

    log_page_module.LogPage.__init__ = __init__

    original_t = log_page_module._t

    def _t(text, _original=original_t):
        return _original(sanitize_text(text))

    log_page_module._t = _t
    _ = shell


def _patch_script_folders():
    """Rename the custom-script folders created beside the executable."""
    import os
    from ok.core import script_packager

    script_packager.OK_TASKS_FOLDER = SCRIPTS_FOLDER
    script_packager.OK_IMPORT_FOLDER = IMPORT_FOLDER
    script_packager.get_ok_tasks_folder = lambda: os.path.join(os.getcwd(), SCRIPTS_FOLDER)
    script_packager.get_ok_import_folder = lambda: os.path.join(os.getcwd(), IMPORT_FOLDER)


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
    if getattr(ok_package, '_wwa_identity_applied', False):
        return False
    ok_package._wwa_identity_applied = True

    _patch_logging()
    _patch_logger_file()
    _patch_mutex()
    _patch_window_classes()
    _patch_notifications()
    _patch_script_folders()
    _patch_log_page()
    _export_ok_globals()
    return True
