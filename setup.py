import os
import pathlib

import setuptools
from Cython.Build import cythonize
from setuptools import Extension

os.environ["PYTHONIOENCODING"] = "utf-8"

ROOT = pathlib.Path(__file__).resolve().parent
EXCLUDE_FILES = {"__init__.py", "identity.py"}


def collect_python_extensions(base_dir):
    """One Extension per .py module under base_dir (and config.py at root).

    __init__.py stays as source: package discovery needs it importable before
    the compiled modules exist, and it carries no logic worth obfuscating.
    identity.py stays as source: its monkey-patches need real Python functions;
    Cython compiles nested defs into non-descriptor builtins that cannot bind
    ``self`` when assigned to class attributes.
    """
    extensions = []
    for path in sorted(pathlib.Path(base_dir).rglob("*.py")):
        if path.name in EXCLUDE_FILES:
            continue
        module = ".".join(path.with_suffix("").parts)
        extensions.append(
            Extension(name=module, language="c++", sources=[str(path)]))
    config_py = ROOT / "config.py"
    if config_py.is_file():
        extensions.append(Extension(name="config", language="c++", sources=["config.py"]))
    print(f"collected {len(extensions)} modules to compile")
    return extensions


extensions = collect_python_extensions("src")

setuptools.setup(
    name="xjtuww",
    version="1.2.0",
    author="xjtu-ww maintainers",
    author_email="",
    description="XJTU-WW automation runtime",
    url="https://github.com/GodRaymond233/xjtu-ww",
    packages=setuptools.find_packages(),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
    ],
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "embedsignature": False,
            "binding": False,
        },
        nthreads=0,
    ),
)
