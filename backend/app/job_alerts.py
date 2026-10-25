"""Durable, opt-in daily scans. The server runs them; a browser tab is not needed."""
import asyncio,base64,hashlib,html,json,os,re,time,secrets
from datetime import datetime,timezone,timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field,field_validator,model_validator
from . import db,config,auth,onboarding,job_search,job_locations,graduation_defaults,role_catalog,provider_connections
from .models import StrictModel,SearchRequest
from .network import ServiceError

router=APIRouter(prefix='/api/job-search',tags=['Job Search'])

def owner(user=Depends(auth.current)):
    onboarding.require_complete(user['id']);return user['id']

def ident(user,kind):return hashlib.sha256((user+':'+kind).encode()).hexdigest()[:32]
def record(user,kind,default):
    rows=db.list_entities(user,kind)
    return rows[0] if rows else {'id':ident(user,kind),'data':default}
def preferences(user,zone=None):
    result=record(user,'job_search_preferences',{'query':{**SearchRequest().model_dump(),'title':'','interests':[]}})
    data=dict(result['data']);data['query']=dict(data['query'])
    # Existing stored choices are manual until the user explicitly restores auto.
    data.setdefault('job_type_mode','manual' if result.get('created_at') else 'automatic')
    data.setdefault('timezone','UTC')
    if zone:data['timezone']=zone
    if data['job_type_mode']=='automatic':data['query']['job_types']=graduation_defaults.for_profile(user,data['timezone'],interests=data['query'].get('interests',[]))['job_types'];data['query']['career_levels']=data['query']['job_types']
    return {**result,'data':data}

def schedule(user):return record(user,'job_alert',Schedule().model_dump())
def save(user,kind,data):return db.save(user,kind,data,record(user,kind,{})['id'])

class SavedSearch(SearchRequest):
    # Clearing the picker is a valid saved preference, but cannot start a scan.
    title:str=Field(default='',max_length=120)
    @field_validator('title')
    @classmethod
    def valid_title(cls,value):
        if value and len(value.strip())<2:raise ValueError('Choose a role with at least two characters.')
        return value.strip()
    @model_validator(mode='after')
    def legacy_title(self):
        if not self.title and self.interests:self.title=self.interests[0]
        return self
class Preferences(StrictModel):
    page_size:Literal[25,50,100]=25
    query:SavedSearch
    job_type_mode:Literal['automatic','manual']|None=None
    timezone:str|None=Field(default=None,max_length=100)
    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls,value):
        if value is not None:
            try:ZoneInfo(value)
            except (ValueError,ZoneInfoNotFoundError):raise ValueError('Choose a valid IANA time zone.')
        return value
    recent_interests:list[str]|None=Field(default=None,max_length=50)
    account_id:str|None=Field(default=None,max_length=64)
    @field_validator('recent_interests')
    @classmethod
    def recent(cls,values):
        if values is None:return None
        seen=set();result=[]
        for value in values:
            value=' '.join(value.split());key=value.casefold()
            if not 2<=len(value)<=80:raise ValueError('Remembered roles must use 2 to 80 characters.')
            if key not in seen:result.append(value);seen.add(key)
        return result
class Interest(StrictModel):
    state:str=Field(pattern='^(saved|dismissed|none)$')
class Schedule(StrictModel):
    enabled:bool=False
    time:str=Field(default='08:00',pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    timezone:str=Field(default='America/Phoenix',max_length=100)
    browser:bool=False
    email_enabled:bool=False
    email:str=Field(default='',max_length=254)
    @field_validator('timezone')
    @classmethod
    def zone(cls,value):
        try:ZoneInfo(value)
        except (ValueError,ZoneInfoNotFoundError):raise ValueError('Choose a valid IANA time zone.')
        return value
    @field_validator('email')
    @classmethod
    def address(cls,value):
        value=value.strip()
        if value and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',value):raise ValueError('Enter a valid recipient email address.')
        return value
class EmailChoice(StrictModel):
    email:str=Field(min_length=3,max_length=254)
    @field_validator('email')
    @classmethod
    def address(cls,v):return Schedule.address(v)
class EmailCode(EmailChoice):
    code:str=Field(pattern=r'^\d{6}$')
class Subscription(StrictModel):
    endpoint:str=Field(max_length=4096)
    keys:dict[str,str]
    @field_validator('endpoint')
    @classmethod
    def safe_endpoint(cls,value):
        p=urlparse(value);host=(p.hostname or '').lower()
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or not(host=='fcm.googleapis.com' or host=='updates.push.services.mozilla.com' or host=='web.push.apple.com' or host.endswith('.push.apple.com')):raise ValueError('Unsupported public browser push endpoint.')
        return value
    @field_validator('keys')
    @classmethod
    def valid_keys(cls,v):
        if set(v)!={'p256dh','auth'}:raise ValueError('Missing browser encryption keys.')
        try:
            if len(base64.urlsafe_b64decode(v['p256dh']+'==='))!=65 or len(base64.urlsafe_b64decode(v['auth']+'==='))!=16:raise ValueError()
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),base64.urlsafe_b64decode(v['p256dh']+'==='))
        except Exception:raise ValueError('Invalid browser encryption keys.') from None
        return v

def init():
    with db.connect() as c:
        c.executescript('''
CREATE TABLE IF NOT EXISTS cc_job_alert_runs(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,day TEXT,state TEXT,lease_until REAL,result TEXT,PRIMARY KEY(user_id,day));
CREATE TABLE IF NOT EXISTS cc_job_seen(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,identity TEXT,PRIMARY KEY(user_id,identity));
CREATE TABLE IF NOT EXISTS cc_job_baselines(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,source TEXT,PRIMARY KEY(user_id,source));
CREATE TABLE IF NOT EXISTS cc_job_deliveries(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,day TEXT,channel TEXT,state TEXT,detail TEXT,PRIMARY KEY(user_id,day,channel));
CREATE TABLE IF NOT EXISTS cc_job_push(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,id TEXT PRIMARY KEY,subscription TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS cc_job_email_verifications(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,email TEXT,code_hash TEXT,expires REAL,attempts INTEGER,verified INTEGER,PRIMARY KEY(user_id,email));
CREATE TABLE IF NOT EXISTS cc_job_email_requests(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,requested_at REAL);
''')

def key_path():return config.VAULT_KEY_FILE.with_name('job-push.pem')
def push_key():
    p=key_path();p.parent.mkdir(parents=True,exist_ok=True)
    if not p.exists():
        key=ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        try:
            fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(key)
        except FileExistsError:pass
    return p

def capabilities(user=None):
    from . import public_job_feeds as feeds
    connection=provider_connections.public(user) if user else {}
    return {'adzuna':bool(user and connection.get('configured') and (connection.get('usage')=='regular' or connection.get('usage')=='manual_trial' and connection.get('manual_trial_allowed'))),'adzuna_connection':provider_connections.public(user) if user else None,'github':True,'employers':feeds.listing(user) if user else [],'employer_catalog_revision':feeds.REVISION,'employer_catalog_attribution':feeds.CATALOG['attribution'],'usajobs_scope':'Shared connection','usajobs':bool(config.USAJOBS_KEY and config.USAJOBS_EMAIL),'email':bool(config.CF_EMAIL_TOKEN and config.CF_EMAIL_ACCOUNT and config.ALERT_FROM),'email_sender':config.ALERT_FROM,'browser_push':True,'scheduler':config.JOB_SCHEDULER_ENABLED,'tech_preset':job_search.TECH,'preset_groups':role_catalog.GROUPS,'role_catalog':[r['label'] for r in role_catalog.CATALOG['roles']],'catalog_version':role_catalog.VERSION,'location_options':job_locations.options(),'location_regions':job_locations.region_details()}

@router.get('/preferences')
def get_preferences(timezone:str|None=None,user=Depends(owner)):
    if timezone:
        try:Schedule.zone(timezone)
        except ValueError:raise HTTPException(422,'Choose a valid IANA time zone.') from None
    with db.connect() as c:pushes=c.execute('SELECT count(*) FROM cc_job_push WHERE user_id=?',(user,)).fetchone()[0]
    return {'preferences':preferences(user,timezone),'schedule':schedule(user),'capabilities':capabilities(user),'enrolled_browsers':pushes,'persisted_timezone':preferences(user)['data']['timezone'],'suggestions':role_catalog.suggestions(user),'graduation_default':graduation_defaults.for_profile(user,preferences(user,timezone)['data']['timezone'],interests=preferences(user,timezone)['data']['query'].get('interests',[]))}

@router.put('/preferences')
def put_preferences(body:Preferences,user=Depends(owner)):
    if body.account_id and body.account_id!=user:raise HTTPException(409,'Your account changed. Reload before saving search preferences.')
    query=body.query.model_dump();query['sources']=[v for v in query['sources'] if v not in ('web','jobspy')];query['refresh']=False
    if not query['sources']:raise ServiceError('Choose at least one non-AI source for saved searches and daily alerts.')
    previous=preferences(user)['data'];mode=body.job_type_mode or previous['job_type_mode'];zone=body.timezone or previous['timezone']
    if body.job_type_mode is None and query['job_types']!=previous['query']['job_types']:mode='manual'
    if mode=='automatic':query['job_types']=graduation_defaults.for_profile(user,zone,interests=query.get('interests',[]))['job_types'];query['career_levels']=query['job_types']
    changed=previous.get('query')!=query
    result=save(user,'job_search_preferences',{'page_size':body.page_size,'query':query,'recent_interests':body.recent_interests if body.recent_interests is not None else previous.get('recent_interests',[]),'job_type_mode':mode,'timezone':zone})
    if changed:
        with db.connect() as c:c.execute('DELETE FROM cc_job_baselines WHERE user_id=?',(user,))
    return result

@router.put('/jobs/{id}/interest')
def interest(id:str,body:Interest,user=Depends(owner)):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT * FROM entities WHERE user_id=? AND id=? AND kind='job'",(user,id)).fetchone()
        if not row:raise HTTPException(404,'Posting not found.')
        data=json.loads(row['payload']);data.update(interest_state=body.state,interest_updated_at=db.now())
        c.execute('UPDATE entities SET payload=?,updated_at=? WHERE user_id=? AND id=?',(json.dumps(data),db.now(),user,id))
    return db.get(user,id,'job')

async def email_api(method,path,payload=None):
    if not capabilities()['email']:raise ServiceError('Email delivery needs a server sending token and verified domain. Browser alerts remain available.')
    try:
        async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
            r=await client.request(method,'https://api.cloudflare.com/client/v4/accounts/'+config.CF_EMAIL_ACCOUNT+'/'+path,headers={'Authorization':'Bearer '+config.CF_EMAIL_TOKEN},json=payload)
            if r.status_code>=400:raise ServiceError('Email provider returned HTTP '+str(r.status_code)+'. Check the server connection and domain setup.')
            value=r.json()
            if not value.get('success'):raise ServiceError('Email provider could not approve this request. Check server configuration.')
            return value.get('result')
    except (httpx.HTTPError,ValueError):raise ServiceError('Email provider could not be reached; delivery is not confirmed.') from None

async def verified_recipient(address):
    rows=await email_api('GET','email/routing/addresses?per_page=200')
    return any(r.get('email','').casefold()==address.casefold() and r.get('verified') for r in rows or [])

@router.post('/email/verify')
async def verify_email(body:EmailChoice,user=Depends(owner)):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        count=c.execute('SELECT count(*) FROM cc_job_email_requests WHERE user_id=? AND requested_at>?',(user,time.time()-86400)).fetchone()[0]
        latest=c.execute('SELECT max(requested_at) FROM cc_job_email_requests WHERE user_id=?',(user,)).fetchone()[0] or 0
        if count>=5 or latest>time.time()-60:raise HTTPException(429,'Wait before requesting another verification email.')
        c.execute('INSERT INTO cc_job_email_requests VALUES(?,?)',(user,time.time()))
    if await verified_recipient(body.email):
        code=''.join(secrets.choice('0123456789') for _ in range(6));digest=hashlib.sha256((user+':'+body.email.casefold()+':'+code).encode()).hexdigest()
        with db.connect() as c:c.execute('INSERT OR REPLACE INTO cc_job_email_verifications VALUES(?,?,?,?,?,?)',(user,body.email.casefold(),digest,time.time()+600,0,0))
        await email_api('POST','email/sending/send',{'to':body.email,'from':config.ALERT_FROM,'subject':'Verify Career Companion job alerts','text':'Your verification code is '+code+'. It expires in 10 minutes. If you did not request this, ignore this message.','html':'<p>Your verification code is <strong>'+code+'</strong>. It expires in 10 minutes.</p>'})
        return {'verified':False,'stage':'code','message':'A six-digit code was sent. Enter it here to verify this recipient for your account.'}
    await email_api('POST','email/routing/addresses',{'email':body.email})
    return {'verified':False,'stage':'provider','message':'Open the provider verification email, then click Verify recipient again to receive your account confirmation code. No mailbox was created.'}

@router.post('/email/confirm')
def confirm_email(body:EmailCode,user=Depends(owner)):
    valid=False
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM cc_job_email_verifications WHERE user_id=? AND email=?',(user,body.email.casefold())).fetchone()
        if row and row['expires']>time.time() and row['attempts']<5:
            digest=hashlib.sha256((user+':'+body.email.casefold()+':'+body.code).encode()).hexdigest()
            valid=secrets.compare_digest(row['code_hash'],digest)
            c.execute('UPDATE cc_job_email_verifications SET attempts=attempts+1,verified=? WHERE user_id=? AND email=?',(int(valid),user,body.email.casefold()))
    if not valid:raise HTTPException(400,'The code is invalid or expired. Request another verification code.')
    return {'verified':True}

def account_email_verified(user,address):
    with db.connect() as c:return bool(c.execute('SELECT 1 FROM cc_job_email_verifications WHERE user_id=? AND email=? AND verified=1',(user,address.casefold())).fetchone())

@router.put('/schedule')
async def put_schedule(body:Schedule,user=Depends(owner)):
    if body.email_enabled and (not body.email or not account_email_verified(user,body.email) or not await verified_recipient(body.email)):raise ServiceError('Verify this recipient before enabling email alerts.')
    if body.enabled and not preferences(user)['data']['query'].get('interests') and not preferences(user)['data']['query'].get('title'):raise ServiceError('Save search interests first.')
    return save(user,'job_alert',body.model_dump())

@router.get('/push-key')
def get_push_key(user=Depends(owner)):
    key=serialization.load_pem_private_key(push_key().read_bytes(),password=None)
    raw=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    return {'public_key':base64.urlsafe_b64encode(raw).rstrip(b'=').decode()}

@router.post('/push')
def subscribe(body:Subscription,user=Depends(owner)):
    id=hashlib.sha256(body.endpoint.encode()).hexdigest()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT user_id FROM cc_job_push WHERE id=?',(id,)).fetchone()
        if existing and existing['user_id']!=user:raise HTTPException(409,'Unenroll this browser from its previous account before connecting another account.')
        c.execute('DELETE FROM cc_job_push WHERE user_id=? AND id=?',(user,id))
        if c.execute('SELECT count(*) FROM cc_job_push WHERE user_id=?',(user,)).fetchone()[0]>=5:raise ServiceError('Remove a browser before enrolling more than five devices.')
        c.execute('INSERT INTO cc_job_push VALUES(?,?,?,?)',(user,id,json.dumps(body.model_dump()),db.now()))
    return {'id':id,'enrolled':True}

@router.delete('/push')
def unsubscribe(body:Subscription,user=Depends(owner)):
    with db.connect() as c:c.execute('DELETE FROM cc_job_push WHERE user_id=? AND id=?',(user,hashlib.sha256(body.endpoint.encode()).hexdigest()))
    return {'enrolled':False}

@router.get('/notifications')
def notifications(user=Depends(owner)):
    with db.connect() as c:
        rows=c.execute('SELECT day,state,result FROM cc_job_alert_runs WHERE user_id=? ORDER BY day DESC LIMIT 30',(user,)).fetchall()
        delivery=c.execute('SELECT day,channel,state,detail FROM cc_job_deliveries WHERE user_id=? ORDER BY day DESC LIMIT 60',(user,)).fetchall()
    return {'runs':[dict(r)|{'result':json.loads(r['result'] or '{}')} for r in rows],'deliveries':[dict(r) for r in delivery]}

def claim(user,day,now):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM cc_job_alert_runs WHERE user_id=? AND day=?',(user,day)).fetchone()
        if row and (row['state']=='done' or row['lease_until']>now):return None
        if row:
            c.execute("UPDATE cc_job_deliveries SET state='unconfirmed',detail='The previous send was interrupted. It is not resent because delivery may already have occurred.' WHERE user_id=? AND day=? AND state='sending'",(user,day))
            c.execute('UPDATE cc_job_alert_runs SET lease_until=? WHERE user_id=? AND day=?',(now+900,user,day));return json.loads(row['result']) if row['result'] else {}
        c.execute('INSERT INTO cc_job_alert_runs VALUES(?,?,?,?,?)',(user,day,'running',now+900,None));return {}

def current_alert(user):
    rows=db.list_entities(user,'job_alert');return rows[0]['data'] if rows else {}

async def deliver(user,day,batch):
    settings=current_alert(user)
    if not settings.get('enabled') or not batch.get('new_jobs'):return
    for channel in ('browser','email'):
        if not settings.get('browser' if channel=='browser' else 'email_enabled'):continue
        # Record intent BEFORE external delivery; uncertain sends are never replayed.
        with db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM cc_job_deliveries WHERE user_id=? AND day=? AND channel=?',(user,day,channel)).fetchone():continue
            c.execute('INSERT INTO cc_job_deliveries VALUES(?,?,?,?,?)',(user,day,channel,'sending','Delivery outcome not confirmed yet.'))
        state='sent';detail='Accepted by delivery service.'
        try:
            if channel=='browser':
                with db.connect() as c:subs=c.execute('SELECT id,subscription FROM cc_job_push WHERE user_id=?',(user,)).fetchall()
                if not subs:raise ServiceError('No enrolled browser. Enable notifications on this device.')
                from pywebpush import webpush,WebPushException
                accepted=0;failed=0
                for sub in subs:
                    try:
                        await asyncio.to_thread(webpush,subscription_info=json.loads(sub['subscription']),data=json.dumps({'title':'Career Companion: new job matches','body':str(len(batch['new_jobs']))+' newly found matches. Open Job Search to review.','url':'/?view=jobs&alerts=1','tag':'job-digest-'+day}),vapid_private_key=str(push_key()),vapid_claims={'sub':('mailto:'+config.ALERT_FROM) if config.ALERT_FROM else 'https://localhost'},ttl=86400,timeout=15)
                        accepted+=1
                    except WebPushException as e:
                        if e.response is not None and e.response.status_code in (404,410):
                            with db.connect() as c:c.execute('DELETE FROM cc_job_push WHERE user_id=? AND id=?',(user,sub['id']))
                        failed+=1
                if not accepted:raise ServiceError('No browser accepted the notification. Re-enroll expired subscriptions.')
                detail=str(accepted)+' browser(s) accepted the notification; '+str(failed)+' failed.'
            else:
                address=settings.get('email','')
                if not account_email_verified(user,address) or not await verified_recipient(address):raise ServiceError('Email recipient verification is missing or revoked.')
                rows=[db.get(user,id,'job') for id in batch['new_jobs']];rows=[r for r in rows if r]
                link=config.ALERT_PUBLIC_ORIGIN+'/?view=jobs&alerts=1'
                lines=['Newly found matches — source publication dates may differ.','']+[r['data']['title']+' — '+r['data'].get('company','')+'\n'+r['data'].get('url','') for r in rows[:25]]+['','Review all matches and turn off email alerts: '+link]
                content='<p>Newly found matches; discovery does not prove that a job just opened.</p><ul>'+''.join('<li><a href="'+html.escape(r['data'].get('url',''),quote=True)+'">'+html.escape(r['data']['title'])+'</a> — '+html.escape(r['data'].get('company',''))+(' · <a style="display:inline-block;min-width:116px;min-height:23px" href="https://www.adzuna.com">Adzuna</a>' if any(s.get('provider')=='adzuna' for s in r['data'].get('sources',[])) else '')+'</li>' for r in rows[:25])+'</ul><p><a href="'+html.escape(link,quote=True)+'">Review all matches or turn off email alerts</a></p>'
                result=await email_api('POST','email/sending/send',{'to':address,'from':{'address':config.ALERT_FROM,'name':'Career Companion'},'subject':str(len(rows))+' newly found job matches','text':'\n'.join(lines),'html':content,'headers':{'List-Unsubscribe':'<'+link+'>'}})
                if address in (result or {}).get('permanent_bounces',[]):raise ServiceError('Recipient bounced; disable email alerts and check the address.')
                if address not in (result or {}).get('delivered',[]) and address not in (result or {}).get('queued',[]):raise ServiceError('Email service did not confirm acceptance.')
        except Exception as e:
            state='unconfirmed';detail=str(e) if isinstance(e,ServiceError) else 'Delivery was not confirmed. Check channel setup; automatic resend is disabled to avoid duplicates.'
        with db.connect() as c:c.execute('UPDATE cc_job_deliveries SET state=?,detail=? WHERE user_id=? AND day=? AND channel=?',(state,detail,user,day,channel))

async def run_daily(user,now=None,force=False):
    if not onboarding.status(user)['completed']:return
    now=now or datetime.now(timezone.utc);settings=current_alert(user)
    if not settings.get('enabled'):return
    saved_query=preferences(user)['data']['query']
    if not saved_query.get('interests') and not saved_query.get('title','').strip():return
    local=now.astimezone(ZoneInfo(settings.get('timezone','America/Phoenix')))
    if not force and local.strftime('%H:%M')<settings.get('time','08:00'):return
    day=local.date().isoformat();saved=claim(user,day,now.timestamp())
    if saved is None:return
    try:
        if not saved:
            request=SearchRequest.model_validate(preferences(user)['data']['query']);request.sources=[v for v in request.sources if v not in ('web','jobspy')];request.refresh=True
            if provider_connections.public(user).get('usage')!='regular':request.sources=[v for v in request.sources if v!='adzuna']
            result=await asyncio.wait_for(job_search.discover(user,request,execution='scheduled'),600)
            __import__(__package__+'.job_results',fromlist=['save_search']).save_search(user,{**result,'scheduled':True},ident(user,'scheduled-search:'+day))
            errors={v['source'] for v in result['sources'] if v['status'] not in ('ok','empty')}
            successes={v['source'] for v in result['sources'] if v['status'] in ('ok','empty')} - errors
            with db.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                known={r[0] for r in c.execute('SELECT identity FROM cc_job_seen WHERE user_id=?',(user,))};baselines={r[0] for r in c.execute('SELECT source FROM cc_job_baselines WHERE user_id=?',(user,))}
                new=[]
                for row in result['jobs']:
                    data=row['data'];key=data.get('source_identity') or data['url'];url_key='url:'+job_search.x.canonical_url(data['url']);source=data.get('origin_key',data.get('sources',[{}])[0].get('provider',''))
                    if not data.get('snapshot_stale') and source in successes and source in baselines and key not in known and url_key not in known and data.get('interest_state')!='dismissed':new.append(row['id'])
                    c.execute('INSERT OR IGNORE INTO cc_job_seen VALUES(?,?)',(user,key))
                    c.execute('INSERT OR IGNORE INTO cc_job_seen VALUES(?,?)',(user,url_key))
                for source in successes:c.execute('INSERT OR IGNORE INTO cc_job_baselines VALUES(?,?)',(user,source))
                saved={'new_jobs':list(dict.fromkeys(new)),'checked_at':db.now(),'sources':result['sources'],'baseline_established':not bool(baselines) and bool(successes),'baseline_pending':not bool(baselines) and not bool(successes),'matched_count':len(result['jobs'])}
                c.execute('UPDATE cc_job_alert_runs SET result=? WHERE user_id=? AND day=?',(json.dumps(saved),user,day))
        await deliver(user,day,saved)
        with db.connect() as c:c.execute('UPDATE cc_job_alert_runs SET state=?,lease_until=0 WHERE user_id=? AND day=?',('done',user,day))
    except asyncio.CancelledError:raise
    except Exception:
        with db.connect() as c:c.execute('UPDATE cc_job_alert_runs SET state=?,lease_until=?,result=? WHERE user_id=? AND day=?',('retry',now.timestamp()+300,json.dumps(saved) if saved else None,user,day))

async def scheduler():
    while True:
        try:
            with db.connect() as c:users=[r[0] for r in c.execute("SELECT DISTINCT user_id FROM entities WHERE kind='job_alert'")]
            for user in users:await run_daily(user)
        except asyncio.CancelledError:raise
        except Exception:pass # Per-run status remains persisted; next tick recovers the lease.
        await asyncio.sleep(60)

@router.post('/check-now')
async def check_now(user=Depends(owner)):
    if not current_alert(user).get('enabled'):raise ServiceError('Save an enabled daily alert before running its daily check. You can use Search jobs without enabling alerts.')
    saved_query=preferences(user)['data']['query']
    if not saved_query.get('interests') and not saved_query.get('title','').strip():raise ServiceError('Choose at least one role before running a daily check.')
    from .main import start_task
    async def work():
        await run_daily(user,force=True)
        return notifications(user)
    return start_task(user,'discovery',work)


def restore_record(user,kind,data):
    if kind=='job_search_preferences':return save(user,kind,Preferences.model_validate(data).model_dump(exclude={'account_id'},exclude_none=True))
    if kind=='job_alert':
        with db.connect() as c:c.execute('DELETE FROM cc_job_email_verifications WHERE user_id=?',(user,))
        return save(user,kind,Schedule.model_validate({**data,'enabled':False,'email_enabled':False,'browser':False}).model_dump())
    return None
