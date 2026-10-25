"""Encrypted provider credentials, scoped to accounts and excluded from backups.

USAJOBS is shared configuration. Adzuna never falls back to installation keys.
"""
import json,re
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from typing import Literal
from . import db,auth,config
from .models import StrictModel
from .network import ServiceError

router=APIRouter(prefix='/api/settings/job-connections',tags=['Account job connections'])

def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS cc_provider_connections(
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      provider TEXT NOT NULL,ciphertext TEXT NOT NULL,revision INTEGER NOT NULL,
      test_only INTEGER NOT NULL,updated_at TEXT NOT NULL,
      PRIMARY KEY(user_id,provider))''')

def row(user):
    with db.connect() as c:return c.execute("SELECT * FROM cc_provider_connections WHERE user_id=? AND provider='adzuna'",(user,)).fetchone()

def public(user):
    r=row(user)
    return {'configured':bool(r and r['ciphertext']),'test_only':bool(r and r['test_only']),'revision':r['revision'] if r else 0,'scope':'account'}

def resolve(user,*,testing=False):
    r=row(user)
    if not r or not r['ciphertext'] or r['test_only'] and not testing:return None
    from .private_answers import unseal
    return unseal(user,'provider:adzuna',r['ciphertext'])

class Adzuna(StrictModel):
    app_id:str=Field(min_length=1,max_length=120)
    app_key:str=Field(min_length=8,max_length=500)
    usage:Literal['test_only','regular']='test_only'
    # A regular connection is an explicit choice after the user checks their plan.

def store(user,body,*,only_if_absent=False):
    from .private_answers import seal
    if any(re.search(r'\s',v) for v in (body.app_id,body.app_key)):raise ServiceError('Enter the application ID and key without spaces.')
    encrypted=seal(user,'provider:adzuna',{'app_id':body.app_id,'app_key':body.app_key})
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        previous=c.execute("SELECT revision FROM cc_provider_connections WHERE user_id=? AND provider='adzuna'",(user,)).fetchone()
        if only_if_absent and previous:return False
        c.execute("INSERT INTO cc_provider_connections VALUES(?,'adzuna',?,?,?,?) ON CONFLICT(user_id,provider) DO UPDATE SET ciphertext=excluded.ciphertext,revision=excluded.revision,test_only=excluded.test_only,updated_at=excluded.updated_at",(user,encrypted,(previous[0] if previous else 0)+1,int(body.usage=='test_only'),db.now()))
    return True

def migrate_trial(user,username,app_id,app_key,verified_email=''):
    """Operator-only migration; caller verifies the owner in each installation.
    No provider call. Never changes an existing (even removed) connection.
    """
    with db.connect() as c:
        account=c.execute('SELECT username FROM users WHERE id=?',(user,)).fetchone()
        membership=c.execute('SELECT email FROM cc_memberships WHERE user_id=?',(user,)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='cc_memberships'").fetchone() else None
    if not account or account['username']!=username or (membership and membership['email'].casefold()!=verified_email.casefold()):raise ValueError('Owner identity does not match this installation.')
    return store(user,Adzuna(app_id=app_id,app_key=app_key),only_if_absent=True)

@router.get('')
def status(user=Depends(auth.current)):
    return {'adzuna':public(user['id']),'usajobs':{'scope':'shared','configured':bool(config.USAJOBS_KEY and config.USAJOBS_EMAIL)}}

@router.put('/adzuna')
def update(body:Adzuna,user=Depends(auth.current)):
    store(user['id'],body)
    return {'adzuna':public(user['id']),'message':'Account connection saved. No test call was made.'}

@router.delete('/adzuna')
def remove(user=Depends(auth.current)):
    with db.connect() as c:
        c.execute("INSERT INTO cc_provider_connections VALUES(?,'adzuna','',1,1,?) ON CONFLICT(user_id,provider) DO UPDATE SET ciphertext='',revision=revision+1,test_only=1,updated_at=excluded.updated_at",(user['id'],db.now()))
    return {'adzuna':public(user['id']),'message':'Adzuna connection removed from this account.'}

@router.post('/adzuna/test')
async def test(user=Depends(auth.current)):
    secret=resolve(user['id'],testing=True)
    if not secret:raise ServiceError('Save an Adzuna connection for this account first.')
    from .integrations import fetch_json
    try:
        await fetch_json('https://api.adzuna.com/v1/api/jobs/us/search/1',{'app_id':secret['app_id'],'app_key':secret['app_key'],'what':'intern','results_per_page':1})
    except Exception:
        # Upstream exceptions may contain a credential-bearing URL. Never echo it.
        raise ServiceError('Adzuna test failed. Check this account’s ID, key, plan and remaining allowance. One test request was attempted.') from None
    return {'message':'Adzuna accepted one test request. Test-only connections remain excluded from normal and daily searches.'}
