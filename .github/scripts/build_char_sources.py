"""Generate portable character sources from the same checkout being compiled."""

import ast
import shutil
import tempfile
from pathlib import Path


def collect_character_sources(root):
    root = Path(root)
    factory = root / 'src' / 'char' / 'CharFactory.py'
    tree = ast.parse(factory.read_text(encoding='utf-8'), filename=str(factory))
    imports = {}
    registry = None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('src.char.'):
            for name in node.names:
                imports[name.asname or name.name] = (name.name, root.joinpath(*node.module.split('.')).with_suffix('.py'))
        elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == '_char_dict_raw' for target in node.targets):
            registry = node.value
    if not isinstance(registry, ast.Dict):
        raise ValueError('Cannot find the built-in character registry')
    symbols = {'BaseChar'}
    for entry in registry.values:
        if not isinstance(entry, ast.Dict):
            raise ValueError('Expected a character registration dictionary')
        symbol = next((value for key, value in zip(entry.keys, entry.values)
                       if isinstance(key, ast.Constant) and key.value == 'cls'), None)
        if not isinstance(symbol, ast.Name):
            raise ValueError('Character registration has no class')
        symbols.add(symbol.id)
    sources = {}
    for symbol in sorted(symbols):
        class_name, path = imports[symbol]
        source = path.read_bytes()
        module = ast.parse(source, filename=str(path))
        if not any(isinstance(node, ast.ClassDef) and node.name == class_name for node in module.body):
            raise ValueError(f'{path} does not define {class_name}')
        sources[f'{class_name}.py'] = source
    return sources


def build_character_sources(root, destination):
    sources = collect_character_sources(root)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='char-sources-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'char_sources'
        staged.mkdir()
        for name, source in sources.items():
            (staged / name).write_bytes(source)
        if destination.exists():
            shutil.rmtree(destination)
        staged.rename(destination)
    return len(sources)


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    count = build_character_sources(root, root / 'build' / 'char_sources')
    print(f'Generated {count} character source snapshots from the current registry.')
