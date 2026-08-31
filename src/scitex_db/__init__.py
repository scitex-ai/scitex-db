"""Database operations module for scitex.

PostgreSQL support is optional and requires ``psycopg2``. All public
symbols are imported lazily via PEP 562 ``__getattr__`` so that
``import scitex_db`` stays under the §10 cold-start budget — Click
runs the CLI once per Tab press, and slow imports break tab-completion.
"""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _v

    try:
        __version__ = _v("scitex-db")
    except PackageNotFoundError:
        __version__ = "0.0.0+local"
    del _v, PackageNotFoundError
except ImportError:  # pragma: no cover — only on ancient Pythons
    __version__ = "0.0.0+local"


_LAZY_ATTRS = {
    "SQLite3": ("._sqlite3._SQLite3", "SQLite3"),
    "PostgreSQL": ("._postgresql._PostgreSQL", "PostgreSQL"),
    "delete_duplicates": ("._delete_duplicates", "delete_duplicates"),
    "delete_sqlite3_duplicates": (
        "._sqlite3._delete_duplicates",
        "delete_sqlite3_duplicates",
    ),
    "inspect": ("._inspect", "inspect"),
    "check_health": ("._check_health", "check_health"),
    "batch_health_check": ("._check_health", "batch_health_check"),
    "register_post_save_hook": ("._observers", "register_post_save_hook"),
    "register_post_load_hook": ("._observers", "register_post_load_hook"),
}


def __getattr__(name: str):
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module_path, attr = target
    try:
        module = import_module(module_path, __name__)
    except ImportError:
        # Optional dep (psycopg2 for PostgreSQL) — return None for back-compat.
        if name == "PostgreSQL":
            return None
        raise
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_ATTRS, "__version__"})


__all__ = [
    "__version__",
    "PostgreSQL",
    "SQLite3",
    "batch_health_check",
    "check_health",
    "delete_duplicates",
    "delete_sqlite3_duplicates",
    "inspect",
    "register_post_load_hook",
    "register_post_save_hook",
]
