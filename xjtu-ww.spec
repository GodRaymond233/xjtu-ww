from pathlib import Path
import os
import re

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

root = Path(SPECPATH)
datas = [(str(root / name), name) for name in ('assets', 'icons', 'i18n', 'workshop_bundle')]
datas += [(str(root / name), '.') for name in ('LICENSE.txt', 'README.md')]
char_sources = root / 'build' / 'char_sources'
if not (char_sources / 'BaseChar.py').is_file():
    raise RuntimeError('Run .github/scripts/build_char_sources.py before compiling and stripping sources.')
datas.append((str(char_sources), 'char_sources'))
# Compiled build: src ships as .pyd extensions; char_sources/ carries the
# character sources the workshop and AI edits read at runtime.
compiled = sorted(root.glob('src/**/*.cp312-win_amd64.pyd'))
if not compiled:
    raise RuntimeError('Compiled src/*.pyd modules are missing; run build_ext first.')
for module in compiled:
    datas.append((str(module), str(module.parent.relative_to(root))))
if (root / 'config.cp312-win_amd64.pyd').is_file():
    datas.append((str(root / 'config.cp312-win_amd64.pyd'), '.'))
hiddenimports = collect_submodules('src')
binaries = collect_dynamic_libs('openvino')
for package in ('ok', 'onnxocr'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    # ok.gui redirects to ok.ui.qt at runtime; its child names are aliases.
    hiddenimports += [name for name in package_imports if not name.startswith('ok.gui.')]

version_file = root / 'build' / 'version.txt'
version_file.parent.mkdir(parents=True, exist_ok=True)
app_version = os.environ.get('APP_VERSION', 'dev')
version_file.write_text(app_version, encoding='utf-8')
datas.append((str(version_file), '.'))
version_match = re.match(r'^v?(\d+)\.(\d+)\.(\d+)(?:-|$)', app_version)
file_version = tuple(map(int, version_match.groups())) + (0,) if version_match else (0, 0, 0, 0)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=file_version, prodvers=file_version),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('FileDescription', 'XJTU-WW'),
            StringStruct('FileVersion', app_version),
            StringStruct('InternalName', 'xjtuww'),
            StringStruct('OriginalFilename', 'xjtu-ww.exe'),
            StringStruct('ProductName', 'XJTU-WW'),
            StringStruct('ProductVersion', app_version),
            StringStruct('Comments', 'Internal XJTU-WW build.'),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),
    ],
)

analysis = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
)
# Qt uses the ICU ABI supplied by Windows, not a third-party copy on PATH.
analysis.binaries = [entry for entry in analysis.binaries
                     if Path(entry[0]).name.lower() != 'icuuc.dll'
                     and not Path(entry[0]).name.lower().startswith('icudt')]
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    # Keep Chinese logs readable on Windows installations using other code pages.
    [('X utf8', None, 'OPTION')],
    exclude_binaries=True,
    name='xjtu-ww',
    console=False,
    icon=str(root / 'icons' / 'icon.png'),
    version=version_info,
    contents_directory='.',
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    name='xjtu-ww',
)
