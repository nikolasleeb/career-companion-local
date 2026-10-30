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
        from . import task_atomic
        conn = sqlite3.connect(config.DB_PATH, timeout=20,factory=task_atomic.Connection)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=20000')
        try:
            storage.configure(conn)
            task_atomic.attach(conn)
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
        from . import account_cleanup,openai_connection_test
        account_cleanup.init(c);openai_connection_test.init(c)
        from . import combined_import
        combined_import.init(c)
        from . import public_job_feeds
        public_job_feeds.init(c)
        from . import job_results
        job_results.init(c)
        from . import job_cache
        job_cache.init(c)
        from . import coach_knowledge
        coach_knowledge.init(c)
        private_answers.init(c)
        private_profile.init(c)
        application_agent.init(c)
        from . import task_atomic
        task_atomic.init(c)
        c.execute("UPDATE tasks SET status='interrupted',error='The application restarted. Your saved inputs remain available; retry the action.',updated_at=? WHERE status IN ('queued','running','cancelling')", (now(),))
        c.execute('DELETE FROM cc_task_stage')
        c.execute("UPDATE entities SET payload=json_set(payload,'$.state','interrupted','$.error','Server restarted. Completed review batches are saved; explicitly resume remaining work.'),updated_at=? WHERE kind='ai_job_match' AND json_extract(payload,'$.state') IN ('queued','running')",(now(),))
        c.execute("DELETE FROM evidence_fts WHERE user_id='public'")
        for passage in json.loads((config.CONTENT_DIR / 'guidance.json').read_text()):
            c.execute('INSERT INTO evidence_fts VALUES(?,?,?,?)', (passage['id'], 'public', 'guidance', json.dumps(passage)))

    private_profile.migrate_statuses()

def decode(row):
    if not row:
        return None
    result = dict(row)
    result['data'] = json.loads(result.pop('payload'))
    return result

def save(user, kind, data, entity_id=None, *, restoring=False):
    entity_id = entity_id or uid()
    timestamp = now()
    with connect() as c:
        from . import saved_names
        if kind in saved_names.CHAT_KINDS or kind=='prep' or restoring and kind=='interview_session':c.execute('BEGIN IMMEDIATE')
        existing = c.execute('SELECT user_id,kind,payload FROM entities WHERE id=?', (entity_id,)).fetchone()
        if existing and (existing['user_id'] != user or existing['kind'] != kind):
            raise ValueError('Record not found')
        if kind in saved_names.CHAT_KINDS and (not existing or data.get('title')!=json.loads(existing['payload']).get('title')):
            data={**data,'title':saved_names.clean(data.get('title'))}
            if restoring:data['title']=saved_names.imported_title(c,user,kind,data['title'])
            saved_names.require_available(c,user,kind,data['title'],entity_id)
        if kind=='prep' and not existing:
            data={**data,'title':saved_names.next_practice(c,user)}
        if restoring and kind=='interview_session' and not saved_names.available(c,user,kind,data.get('title',''),entity_id):
            data={**data,'title':saved_names.next_interview(c,user,data['kind'])}
        if kind=='experience':
            from . import project_relations
            old=json.loads(existing['payload']) if existing else {}
            if existing:
                for field in project_relations.FIELDS:
                    if field not in data:data={**data,field:old.get(field,[])}
            project_relations.validate(c,user,data,old,restoring=restoring)
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
        row=c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone()
        public=json.loads(row['settings']) if row else {}
    if not row:return public
    from . import private_profile
    return {**public,**private_profile.authorization(user)}

def update_settings(user, changes):
    from . import private_profile,private_answers
    if any(k in changes for k in private_profile.AUTH_FIELDS):private_answers.key()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        private_profile.update_settings(c,user,changes)
    return settings(user)
