"""Windows startup and shell links."""

import ctypes
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
RUNAS_USER = 0x2000
FORCE_NO_LINKTRACK = 0x40000


def ensure_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    # The manifest normally elevates frozen builds before Python runs.
    if ('runasinvoker' in os.environ.get('__COMPAT_LAYER', '').casefold()
            or '--xjtu-admin-requested' in sys.argv):
        raise PermissionError('XJTU-WW requires administrator privileges. Remove RunAsInvoker compatibility settings.')
    restart_as_admin()


def restart_as_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    arguments = sys.argv[1:] if getattr(sys, 'frozen', False) else [str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
    arguments = [*arguments, '--xjtu-admin-requested']
    result = ctypes.windll.shell32.ShellExecuteW(
        None, 'runas', sys.executable, subprocess.list2cmdline(arguments), os.getcwd(), 1)
    if result <= 32:
        raise OSError(f'Unable to restart XJTU-WW as administrator ({result}).')
    raise SystemExit(0)


def _link_flags(path):
    data = path.read_bytes()
    if len(data) < 76 or data[:4] != b'L\x00\x00\x00':
        raise ValueError(f'Invalid shell link: {path}')
    return int.from_bytes(data[20:24], 'little')


def write_shortcut(path, target, arguments, working_dir, name, icon, run_as_admin):
    """Edit IShellLink in place without Resolve, retaining user arguments and flags."""
    import pythoncom
    from win32com.shell import shell

    path = Path(path)
    pythoncom.CoInitialize()
    try:
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                          shell.IID_IShellLink)
        persist = link.QueryInterface(pythoncom.IID_IPersistFile)
        exists = path.exists()
        flags = _link_flags(path) if exists else 0
        if exists:
            persist.Load(str(path))
        old_target = link.GetPath(shell.SLGP_RAWPATH)[0] if exists else ''
        changed = not exists or os.path.normcase(old_target) != os.path.normcase(target)
        if changed:
            link.SetPath(str(target))
            link.SetWorkingDirectory(str(working_dir))
            if not exists:
                link.SetArguments(arguments or '')
                link.SetDescription(name)
                link.SetIconLocation(str(icon or target), 0)
            elif link.GetIconLocation()[0].casefold() == old_target.casefold():
                link.SetIconLocation(str(target), 0)
            persist.Save(str(path), 1)
        current = _link_flags(path)
        updated = current | (flags & RUNAS_USER) | FORCE_NO_LINKTRACK | (RUNAS_USER if run_as_admin else 0)
        if current != updated:
            with path.open('r+b') as output:
                output.seek(20)
                output.write(updated.to_bytes(4, 'little'))
            changed = True
        return changed
    finally:
        pythoncom.CoUninitialize()


def repair_shortcuts(root, directories=None):
    """Repair only links owned by this install, including legacy moved targets."""
    import pythoncom
    from win32com.shell import shell, shellcon

    root = Path(root).resolve()
    target = root / 'xjtu-ww.exe'
    if directories is None:
        directories = [Path(shell.SHGetFolderPath(0, folder, 0, 0)) for folder in
                       (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_PROGRAMS)]
        directories.append(Path(os.environ['APPDATA']) / 'Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar')
    changed = []
    pythoncom.CoInitialize()
    try:
        for directory in directories:
            for path in Path(directory).rglob('*.lnk'):
                try:
                    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                                      shell.IID_IShellLink)
                    link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(path))
                    old = Path(link.GetPath(shell.SLGP_RAWPATH)[0])
                    legacy = (old.name.casefold() == target.name and old.parent.name == 'previous'
                              and old.parent.parent.name.startswith('.xjtu-ww-update-')
                              and old.parent.parent.parent == root.parent
                              and Path(link.GetWorkingDirectory()) == root)
                    if old == target or legacy:
                        if write_shortcut(path, str(target), '', str(root), 'XJTU-WW', str(target), False):
                            changed.append(str(path))
                except (OSError, ValueError, pythoncom.com_error) as error:
                    logger.warning('Could not repair shortcut %s: %s', path, error)
    finally:
        pythoncom.CoUninitialize()
    return changed


def apply():
    import ok
    import pyappify.shortcut as shortcut
    from ok.util import process

    if getattr(ok, '_xjtu_windows_applied', False):
        return
    process.restart_as_admin = restart_as_admin
    # Qt imports this function lazily; the package export serves older adapters.
    ok.restart_as_admin = restart_as_admin
    main_window = sys.modules.get('ok.ui.qt.MainWindow')
    if main_window is not None:
        main_window.restart_as_admin = restart_as_admin
    shortcut._write_shortcut = write_shortcut
    original_command = shortcut._app_command

    def app_command(working_dir, profile, command):
        if getattr(sys, 'frozen', False):
            return sys.executable, []
        return original_command(working_dir, profile, command)

    shortcut._app_command = app_command
    ok._xjtu_windows_applied = True
