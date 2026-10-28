"""Account-owned server secrets. Never included in profile/record backups."""
import json
import os
import tempfile
import hashlib,uuid
from . import config


def path(user):
    return config.DATA_DIR/'credentials'/(user+'.json')


def get(user):
    if not user:return ''
    try:return json.loads(path(user).read_text()).get('openai_key','')
    except (FileNotFoundError,ValueError,OSError):return ''


def save(user,key):
    from . import storage
    target=path(user)
    storage.write_bytes(target,json.dumps({'openai_key':key,'revision':uuid.uuid4().hex}).encode())
    os.chmod(target.parent,0o700)


def remove(user):
    path(user).unlink(missing_ok=True)


def effective(user):
    return get(user) or (config.OPENAI_KEY if config.ALLOW_SERVER_AI_KEY else '')


def revision(user):
    try:
        value=json.loads(path(user).read_text());key=value.get('openai_key','')
        return (value.get('revision') or hashlib.sha256(key.encode()).hexdigest()) if key else ''
    except (FileNotFoundError,ValueError,OSError):return ''
