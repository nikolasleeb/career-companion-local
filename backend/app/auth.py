import hashlib
import secrets
import time
from collections import defaultdict, deque
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from fastapi import HTTPException, Request
from . import db, config

hasher = PasswordHasher()
attempts = defaultdict(deque)

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def throttle(key):
    queue = attempts[key]
    current = time.time()
    while queue and queue[0] < current - 300:
        queue.popleft()
    if len(queue) >= 10:
        raise HTTPException(429, 'Too many attempts. Try again in five minutes.')
    queue.append(current)
    if len(attempts) > 5000:
        for name in list(attempts)[:1000]:
            if not attempts[name] or attempts[name][-1] < current - 300:
                attempts.pop(name, None)

def verify(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False

def issue(response, user):
    token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
    with db.connect() as c:
        c.execute('DELETE FROM sessions WHERE expires_at < ?', (time.time(),))
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token), user, csrf, time.time() + 7*86400))
    response.set_cookie('next_step_session', token, max_age=7*86400, httponly=True, secure=config.COOKIE_SECURE, samesite='strict', path='/')
    return csrf

def current(request: Request):
    token = request.cookies.get('next_step_session', '')
    with db.connect() as c:
        row = c.execute('SELECT u.id,u.username,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?', (digest(token), time.time())).fetchone()
    if not row:
        raise HTTPException(401, 'Sign in to your local account.')
    if request.method not in ('GET','HEAD','OPTIONS'):
        provided = request.headers.get('X-CSRF-Token', '')
        if not provided or not secrets.compare_digest(provided, row['csrf']):
            raise HTTPException(403, 'Your session needs to be refreshed. Reload and try again.')
    return dict(row)
