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
    target=path(user);target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(target.parent,0o700)
    fd,temp=tempfile.mkstemp(dir=target.parent,prefix='.key-')
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump({'openai_key':key},stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temp,target)
        os.chmod(target,0o600)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def remove(user):
    path(user).unlink(missing_ok=True)


def effective(user):
    return get(user) or (config.OPENAI_KEY if config.ALLOW_SERVER_AI_KEY else '')
