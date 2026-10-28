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
    if 'usage_mode' not in {r[1] for r in c.execute('PRAGMA table_info(cc_provider_connections)')}:
        c.execute("ALTER TABLE cc_provider_connections ADD COLUMN usage_mode TEXT NOT NULL DEFAULT 'test_only'")
        c.execute("UPDATE cc_provider_connections SET usage_mode='regular' WHERE test_only=0")
    c.execute('''CREATE TABLE IF NOT EXISTS cc_adzuna_attempts(
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      request_id TEXT NOT NULL,role TEXT NOT NULL,attempted_at TEXT NOT NULL,
      PRIMARY KEY(user_id,request_id,role))''')

def row(user):
    with db.connect() as c:return c.execute("SELECT * FROM cc_provider_connections WHERE user_id=? AND provider='adzuna'",(user,)).fetchone()

def public(user):
    r=row(user)
    mode=r['usage_mode'] if r else 'test_only'
    with db.connect() as c:attempts=c.execute('SELECT count(*) FROM cc_adzuna_attempts WHERE user_id=?',(user,)).fetchone()[0]
    return {'configured':bool(r and r['ciphertext']),'test_only':mode=='test_only','usage':mode,'manual_trial_allowed':trial_owner(user),'installation_requests':attempts,'revision':r['revision'] if r else 0,'scope':'account'}

def trial_owner(user):
    # Deployment-specific allowlist, not a username that another installation can register.
    return bool(getattr(config,'PRODUCTION',False) and bool(getattr(config,'MANUAL_TRIAL_OWNER_ID','')) and user==config.MANUAL_TRIAL_OWNER_ID)

def resolve(user,*,testing=False,manual=False):
    r=row(user)
    if not r or not r['ciphertext']:return None
    if not testing and r['usage_mode']!='regular' and not (manual and r['usage_mode']=='manual_trial' and trial_owner(user)):return None
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
        c.execute("INSERT INTO cc_provider_connections(user_id,provider,ciphertext,revision,test_only,updated_at,usage_mode) VALUES(?,'adzuna',?,?,?,?,?) ON CONFLICT(user_id,provider) DO UPDATE SET ciphertext=excluded.ciphertext,revision=excluded.revision,test_only=excluded.test_only,updated_at=excluded.updated_at,usage_mode=excluded.usage_mode",(user,encrypted,(previous[0] if previous else 0)+1,int(body.usage!='regular'),db.now(),body.usage))
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

class Usage(StrictModel):
    usage:Literal['test_only','manual_trial','regular']

@router.patch('/adzuna/mode')
def change_mode(body:Usage,user=Depends(auth.current)):
    uid=user['id']
    if body.usage=='manual_trial' and not trial_owner(uid):raise HTTPException(403,'Manual trial is enabled only for the hosted pilot owner.')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute("SELECT * FROM cc_provider_connections WHERE user_id=? AND provider='adzuna'",(uid,)).fetchone()
        if not existing or not existing['ciphertext']:raise HTTPException(400,'Save your account connection first.')
        if existing['usage_mode']!=body.usage:
            c.execute("UPDATE cc_provider_connections SET usage_mode=?,test_only=?,revision=revision+1,updated_at=? WHERE user_id=? AND provider='adzuna'",(body.usage,int(body.usage!='regular'),db.now(),uid))
    return {'adzuna':public(uid),'message':'Connection use changed. Your encrypted key is unchanged; no request was made.'}

def claim_attempt(user,request_id,role):
    """Durable claim before sending; crashes never automatically retry a trial call."""
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        count=c.execute('SELECT count(*) FROM cc_adzuna_attempts WHERE user_id=? AND request_id=?',(user,request_id)).fetchone()[0]
        if count>=2:return False
        result=c.execute('INSERT OR IGNORE INTO cc_adzuna_attempts VALUES(?,?,?,?)',(user,request_id,role.casefold(),db.now()))
        return result.rowcount==1

@router.delete('/adzuna')
def remove(user=Depends(auth.current)):
    with db.connect() as c:
        c.execute("INSERT INTO cc_provider_connections(user_id,provider,ciphertext,revision,test_only,updated_at,usage_mode) VALUES(?,'adzuna','',1,1,?,'test_only') ON CONFLICT(user_id,provider) DO UPDATE SET ciphertext='',revision=revision+1,test_only=1,usage_mode='test_only',updated_at=excluded.updated_at",(user['id'],db.now()))
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

api_router=APIRouter(prefix='/api/settings/api-connections',tags=['Connection overview'])
@api_router.get('')
def overview(user=Depends(auth.current)):
    from . import credentials
    own=bool(credentials.get(user['id']));shared=bool(config.OPENAI_KEY and config.ALLOW_SERVER_AI_KEY)
    rows=[{'id':'openai','name':'OpenAI','manager':'account','configured':own,'status':'saved_not_tested' if own else 'not_configured','purpose':'AI writing, career guidance and interview practice'},
          {'id':'adzuna','name':'Adzuna','manager':'account','configured':public(user['id'])['configured'],'status':'saved_not_tested' if public(user['id'])['configured'] else 'not_configured','purpose':'Optional additional job listings'},
          {'id':'onet','name':'O*NET','manager':'server','configured':bool(config.ONET_KEY),'status':'configured' if config.ONET_KEY else 'not_configured','purpose':'Optional live occupational services; Career Explorer browsing uses bundled data'},
          {'id':'usajobs','name':'USAJOBS','manager':'server','configured':bool(config.USAJOBS_KEY and config.USAJOBS_EMAIL),'status':'configured' if config.USAJOBS_KEY and config.USAJOBS_EMAIL else 'not_configured','purpose':'Federal job listings'}]
    if config.ALLOW_SERVER_AI_KEY:rows.append({'id':'installation-openai','name':'OpenAI installation fallback','manager':'server','configured':shared,'status':'configured' if shared else 'not_configured','purpose':'Optional installation-level AI fallback; existing account-key requirements still apply'})
    return {'providers':rows,'deployment':'hosted' if getattr(config,'PRODUCTION',False) else 'local','provider_checks_performed':False}
