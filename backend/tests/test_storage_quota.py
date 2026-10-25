"""Exercise quota boundaries with small real SQLite databases and files."""
import concurrent.futures
import sqlite3
import pytest
from app import config, db, storage


@pytest.fixture
def quota(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'DB_PATH', tmp_path / 'career.sqlite3')
    monkeypatch.setenv('HOSTED_DATA_LIMIT_BYTES', '131072')
    with db.connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE records(value BLOB)')
        c.execute('INSERT INTO records VALUES(?)', (b'original',))
    return tmp_path


def test_database_growth_rolls_back_and_existing_data_remains_readable(quota):
    with pytest.raises(storage.StorageFull):
        with db.connect() as c:
            c.execute('INSERT INTO records VALUES(?)', (b'x' * 200000,))
    with db.connect() as c:
        assert c.execute('SELECT value FROM records').fetchall()[0][0] == b'original'
        assert c.execute('SELECT count(*) FROM records').fetchone()[0] == 1
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert storage.usage_bytes() <= storage.limit_bytes()


def test_files_and_database_share_one_quota(quota):
    storage.write_bytes(quota / 'uploads' / 'one', b'a' * 100000)
    with pytest.raises(storage.StorageFull):
        with db.connect() as c:
            c.execute('INSERT INTO records VALUES(?)', (b'b' * 50000,))
    with pytest.raises(storage.StorageFull):
        storage.write_bytes(quota / 'uploads' / 'two', b'c' * 40000)
    assert not (quota / 'uploads' / 'two').exists()
    assert storage.usage_bytes() <= storage.limit_bytes()


def test_concurrent_file_writers_cannot_both_consume_same_space(quota):
    def write(i):
        try:
            storage.write_bytes(quota / 'uploads' / str(i), b'x' * 80000)
            return True
        except storage.StorageFull:
            return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(write, range(2))) == 1
    assert storage.usage_bytes() <= storage.limit_bytes()


def test_replacement_and_deletion_reclaim_capacity(quota):
    target = quota / 'uploads' / 'one'
    storage.write_bytes(target, b'a' * 100000)
    storage.write_bytes(target, b'b' * 100000)
    with pytest.raises(storage.StorageFull):
        storage.write_bytes(target, b'c' * 200000)
    assert target.read_bytes() == b'b' * 100000
    target.unlink()
    storage.write_bytes(quota / 'uploads' / 'two', b'c' * 100000)


def test_background_transactions_are_limited_without_http_requests(quota):
    def write():
        with db.connect() as c:
            c.execute('INSERT INTO records VALUES(?)', (b'x' * 200000,))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(storage.StorageFull):
            pool.submit(write).result(timeout=5)


def test_lowered_quota_does_not_truncate_or_prevent_reads(quota, monkeypatch):
    monkeypatch.setenv('HOSTED_DATA_LIMIT_BYTES', '1')
    with db.connect() as c:
        assert c.execute('SELECT value FROM records').fetchone()[0] == b'original'


def test_no_limit_for_local_installation(quota, monkeypatch):
    monkeypatch.delenv('HOSTED_DATA_LIMIT_BYTES')
    storage.write_bytes(quota / 'uploads' / 'large', b'x' * 200000)
    with db.connect() as c:
        c.execute('INSERT INTO records VALUES(?)', (b'x' * 200000,))
