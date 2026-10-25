"""Account-owned server secrets. Never included in profile/record backups."""
import json
import os
import tempfile
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
    storage.write_bytes(target,json.dumps({'openai_key':key}).encode())
    os.chmod(target.parent,0o700)


def remove(user):
    path(user).unlink(missing_ok=True)


def effective(user):
    return get(user) or (config.OPENAI_KEY if config.ALLOW_SERVER_AI_KEY else '')
