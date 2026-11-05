from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

root = Path(SPECPATH)
datas = [(str(root / name), name) for name in ('assets', 'icons', 'i18n')]
datas += [(str(root / name), '.') for name in ('LICENSE.txt', 'README.md')]
# The workshop reads and exports built-in character source files.
datas += collect_data_files('src', include_py_files=True)
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
version_file.write_text(os.environ.get('APP_VERSION', 'dev'), encoding='utf-8')
datas.append((str(version_file), '.'))

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
    contents_directory='.',
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    name='xjtu-ww',
)
