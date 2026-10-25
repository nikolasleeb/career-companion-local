"""Quota for persistent application data, independent of Docker's shared disk.

One uvicorn worker is required. Database transactions and file replacements share
the same reentrant lock, including work performed by background threads. SQLite
WAL/journal files are transient copies and excluded from the logical data quota.
"""
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from . import config
from .network import ServiceError

LOCK = threading.RLock()


class StorageFull(ServiceError):
    def __init__(self):
        super().__init__('Hosted storage is full. Existing data is preserved. Delete unneeded files or ask the owner to increase the storage limit, then retry.')


def limit_bytes():
    return max(0, int(os.environ.get('HOSTED_DATA_LIMIT_BYTES', '0')))


@contextmanager
def guard():
    if limit_bytes():
        with LOCK:
            yield
    else:
        yield


def usage_bytes(connection=None):
    total = 0
    transient = {config.DB_PATH.name + suffix for suffix in ('-wal', '-shm', '-journal')}
    for root, dirs, files in os.walk(config.DATA_DIR, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        for name in files:
            path = Path(root) / name
            if path.is_symlink() or name.startswith('.storage-'):
                continue
            if path.parent == config.DATA_DIR and name in transient:
                continue
            if connection is not None and path == config.DB_PATH:
                continue
            try:
                total += path.stat().st_size
            except FileNotFoundError:
                pass
    if connection is not None:
        total += connection.execute('PRAGMA page_count').fetchone()[0] * connection.execute('PRAGMA page_size').fetchone()[0]
    return total


def ensure_capacity(additional=0, connection=None):
    limit = limit_bytes()
    if limit and usage_bytes(connection) + additional > limit:
        raise StorageFull()


def configure(connection):
    limit = limit_bytes()
    if not limit:
        return
    page_size = connection.execute('PRAGMA page_size').fetchone()[0]
    pages = connection.execute('PRAGMA page_count').fetchone()[0]
    other = usage_bytes(connection) - pages * page_size
    # Never truncate an existing database, even when an operator lowers a quota.
    maximum = max(pages, 1, (limit - other) // page_size)
    connection.execute('PRAGMA max_page_count=' + str(maximum))


def validate_commit(connection):
    if limit_bytes() and connection.total_changes:
        ensure_capacity(connection=connection)


def is_full(error):
    return isinstance(error, sqlite3.DatabaseError) and getattr(error, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL


def write_bytes(path, raw, mode=0o600):
    """Check the combined quota and atomically replace a persistent file."""
    path = Path(path)
    with guard():
        previous = path.stat().st_size if path.exists() else 0
        ensure_capacity(len(raw) - previous)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.storage-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
