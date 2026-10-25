import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from . import config, storage

def now():
    return datetime.now(timezone.utc).isoformat()

def uid():
    return uuid.uuid4().hex

@contextmanager
def connect():
    with storage.guard():
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=20000')
        try:
            storage.configure(conn)
            yield conn
            storage.validate_commit(conn)
            conn.commit()
        except Exception as error:
            conn.rollback()
            if storage.is_full(error):
                raise storage.StorageFull() from None
            raise
        finally:
            conn.close()

def init():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        version = c.execute('PRAGMA user_version').fetchone()[0]
        if version < 1:
            c.executescript('''
            CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, settings TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, csrf TEXT NOT NULL, expires_at REAL NOT NULL);
            CREATE TABLE entities(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX entities_user_kind ON entities(user_id,kind,created_at DESC);
            CREATE TABLE tasks(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX tasks_user ON tasks(user_id,status,kind);
            CREATE VIRTUAL TABLE evidence_fts USING fts5(id UNINDEXED,user_id UNINDEXED,kind UNINDEXED,text);
            PRAGMA user_version=1;
            ''')
        from . import private_answers, private_profile, application_agent
        from . import provider_connections
        provider_connections.init(c)
        from . import public_job_feeds
        public_job_feeds.init(c)
        from . import job_results
        job_results.init(c)
        private_answers.init(c)
        private_profile.init(c)
        application_agent.init(c)
        c.execute("UPDATE tasks SET status='interrupted',error='The application restarted. Your saved inputs remain available; retry the action.',updated_at=? WHERE status IN ('queued','running')", (now(),))
        c.execute("UPDATE entities SET payload=json_set(payload,'$.state','interrupted','$.error','Server restarted. Completed review batches are saved; explicitly resume remaining work.'),updated_at=? WHERE kind='ai_job_match' AND json_extract(payload,'$.state') IN ('queued','running')",(now(),))
        c.execute("DELETE FROM evidence_fts WHERE user_id='public'")
        for passage in json.loads((config.CONTENT_DIR / 'guidance.json').read_text()):
            c.execute('INSERT INTO evidence_fts VALUES(?,?,?,?)', (passage['id'], 'public', 'guidance', json.dumps(passage)))

def decode(row):
    if not row:
        return None
    result = dict(row)
    result['data'] = json.loads(result.pop('payload'))
    return result

def save(user, kind, data, entity_id=None):
    entity_id = entity_id or uid()
    timestamp = now()
    with connect() as c:
        existing = c.execute('SELECT user_id,kind FROM entities WHERE id=?', (entity_id,)).fetchone()
        if existing and (existing['user_id'] != user or existing['kind'] != kind):
            raise ValueError('Record not found')
        if existing:
            c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=?', (json.dumps(data), timestamp, entity_id))
        else:
            c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?)', (entity_id, user, kind, json.dumps(data), timestamp, timestamp))
        from . import onboarding
        onboarding.profile_added(c,user,kind,data)
        c.execute('DELETE FROM evidence_fts WHERE id=? AND user_id=?', (entity_id, user))
        if kind == 'experience' and data.get('confirmed'):
            c.execute('INSERT INTO evidence_fts VALUES(?,?,?,?)', (entity_id, user, kind, json.dumps(data)))
    return get(user, entity_id, kind)

def get(user, entity_id, kind=None):
    with connect() as c:
        row = c.execute('SELECT * FROM entities WHERE id=? AND user_id=?', (entity_id, user)).fetchone()
    result = decode(row)
    return result if result and (not kind or kind == result['kind']) else None

def list_entities(user, kind):
    with connect() as c:
        return [decode(r) for r in c.execute('SELECT * FROM entities WHERE user_id=? AND kind=? ORDER BY created_at DESC', (user, kind))]

def delete(user, entity_id):
    with connect() as c:
        c.execute('DELETE FROM evidence_fts WHERE id=? AND user_id=?', (entity_id, user))
        return c.execute('DELETE FROM entities WHERE id=? AND user_id=?', (entity_id, user)).rowcount > 0

def retrieve(user, query, limit=16):
    words = list(dict.fromkeys(re.findall(r'[a-zA-Z][a-zA-Z0-9]{1,25}', query.lower())))[:45]
    ignored = {'the','and','with','for','you','your','this','that','will','from','have','are','our','work','job'}
    match = ' OR '.join('"' + word + '"' for word in words if word not in ignored)
    with connect() as c:
        rows = c.execute('SELECT * FROM evidence_fts WHERE evidence_fts MATCH ? AND (user_id=? OR user_id=?) ORDER BY rank LIMIT ?', (match, user, 'public', limit)).fetchall() if match else []
        results = [{'id':r['id'], 'kind':r['kind'], 'data':json.loads(r['text'])} for r in rows]
    # A short student profile should be available in full, even when terminology differs.
    seen = {r['id'] for r in results}
    for r in list_entities(user, 'experience'):
        if r['data'].get('confirmed') and r['id'] not in seen and len(results) < 30:
            results.append({'id':r['id'], 'kind':'experience', 'data':r['data']})
    return results

def settings(user):
    with connect() as c:
        row = c.execute('SELECT settings FROM users WHERE id=?', (user,)).fetchone()
        return json.loads(row['settings']) if row else {}

def update_settings(user, changes):
    updated = {**settings(user), **changes}
    with connect() as c:
        c.execute('UPDATE users SET settings=? WHERE id=?', (json.dumps(updated), user))
    return updated
