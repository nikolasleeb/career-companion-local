"""Manual job-search preferences and inert compatibility for retired alerts."""
import hashlib,json,re
from typing import Literal
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
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
    data=dict(result['data']);data['query']=SearchRequest.upgrade_public_sources(dict(data['query']));data['query'].setdefault('employer_source_version',1)
    # Existing stored choices are manual until the user explicitly restores auto.
    data.setdefault('job_type_mode','manual' if result.get('created_at') else 'automatic')
    data.setdefault('timezone','UTC')
    if zone:data['timezone']=zone
    if data['job_type_mode']=='automatic':data['query']['job_types']=graduation_defaults.for_profile(user,data['timezone'],interests=data['query'].get('interests',[]))['job_types'];data['query']['career_levels']=data['query']['job_types']
    return {**result,'data':data}

def location_values(values):
    seen=set();result=[]
    for value in values:
        value=' '.join(str(value).split());key=value.casefold()
        if 2<=len(value)<=120 and key not in seen:result.append(value);seen.add(key)
    return result

def remembered_locations(user):
    data=preferences(user)['data']
    # Recover available earlier searches, even if they predate location history.
    queries=[data['query'],*((r['data'].get('query') or {}) for r in db.list_entities(user,'search'))]
    old=[v for query in queries for v in (query.get('locations') or [query.get('location','')])]
    return location_values([*data.get('location_history',[]),*old])

def save_preferences(user,data,location=None,history=()):
    from .resume_conversation import write
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT id,payload FROM entities WHERE user_id=? AND kind='job_search_preferences' ORDER BY created_at DESC LIMIT 1",(user,)).fetchone()
        previous=json.loads(row['payload']) if row else {}
        value=dict(data) if data is not None else previous
        value.setdefault('query',{**SearchRequest().model_dump(),'title':'','interests':[]})
        if not row:value.setdefault('job_type_mode','automatic');value.setdefault('timezone','UTC')
        value['location_history']=location_values(([location] if location else [])+list(history)+value.get('location_history',[])+previous.get('location_history',[]))
        id=write(c,user,'job_search_preferences',value,row['id'] if row else ident(user,'job_search_preferences'))
    return db.get(user,id,'job_search_preferences')

class LocationEntry(StrictModel):
    account_id:str|None=Field(default=None,max_length=64)
    history:list[str]=Field(default_factory=list)
    @field_validator('history')
    @classmethod
    def valid_history(cls,values):
        if any(not 2<=len(' '.join(v.split()))<=120 for v in values):raise ValueError('Remembered locations must use 2 to 120 characters.')
        return location_values(values)
    value:str=Field(min_length=2,max_length=120)
    @field_validator('value')
    @classmethod
    def normalized(cls,value):
        value=' '.join(value.split())
        if len(value)<2:raise ValueError('Use at least two characters for a location.')
        return value

@router.post('/locations')
def remember_location(body:LocationEntry,user=Depends(owner)):
    if body.account_id and body.account_id!=user:raise HTTPException(409,'Your account changed. Reload before saving a location.')
    save_preferences(user,None,body.value,body.history)
    return {'locations':remembered_locations(user)}

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
    location_history:list[str]|None=None
    @field_validator('location_history')
    @classmethod
    def locations(cls,values):
        if values is None:return None
        if any(not 2<=len(' '.join(v.split()))<=120 for v in values):raise ValueError('Remembered locations must use 2 to 120 characters.')
        return location_values(values)
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

def capabilities(user=None):
    from . import public_job_feeds as feeds
    connection=provider_connections.public(user) if user else {}
    return {'adzuna':bool(user and connection.get('configured') and (connection.get('usage')=='regular' or connection.get('usage')=='manual_trial' and connection.get('manual_trial_allowed'))),'adzuna_connection':provider_connections.public(user) if user else None,'github':True,'employers':feeds.listing(user) if user else [],'employer_catalog_revision':feeds.REVISION,'employer_catalog_attribution':feeds.CATALOG['attribution'],'usajobs_scope':'Shared connection','usajobs':bool(config.USAJOBS_KEY and config.USAJOBS_EMAIL),'email':False,'email_sender':'','browser_push':False,'scheduler':False,'alerts_retired':True,'tech_preset':job_search.TECH,'preset_groups':role_catalog.GROUPS,'role_catalog':[r['label'] for r in role_catalog.CATALOG['roles']],'catalog_version':role_catalog.VERSION,'location_options':job_locations.options(),'location_groups':job_locations.groups(),'location_regions':job_locations.region_details()}

@router.get('/preferences')
def get_preferences(timezone:str|None=None,user=Depends(owner)):
    if timezone:
        try:Schedule.zone(timezone)
        except ValueError:raise HTTPException(422,'Choose a valid IANA time zone.') from None
    return {'preferences':{**preferences(user,timezone),'data':{**preferences(user,timezone)['data'],'location_history':remembered_locations(user)}},'schedule':{'id':ident(user,'job_alert'),'data':Schedule().model_dump()},'capabilities':capabilities(user),'enrolled_browsers':0,'persisted_timezone':preferences(user)['data']['timezone'],'suggestions':role_catalog.suggestions(user),'graduation_default':graduation_defaults.for_profile(user,preferences(user,timezone)['data']['timezone'],interests=preferences(user,timezone)['data']['query'].get('interests',[]))}

@router.put('/preferences')
def put_preferences(body:Preferences,user=Depends(owner)):
    if body.account_id and body.account_id!=user:raise HTTPException(409,'Your account changed. Reload before saving search preferences.')
    query=body.query.model_dump();query['sources']=[v for v in query['sources'] if v not in ('web','jobspy')];query['refresh']=False
    if not query['sources']:raise ServiceError('Choose at least one non-AI source for saved searches.')
    previous=preferences(user)['data'];mode=body.job_type_mode or previous['job_type_mode'];zone=body.timezone or previous['timezone']
    if body.job_type_mode is None and query['job_types']!=previous['query']['job_types']:mode='manual'
    if mode=='automatic':query['job_types']=graduation_defaults.for_profile(user,zone,interests=query.get('interests',[]))['job_types'];query['career_levels']=query['job_types']
    result=save_preferences(user,{'location_history':body.location_history or [],'page_size':body.page_size,'query':query,'recent_interests':body.recent_interests if body.recent_interests is not None else previous.get('recent_interests',[]),'job_type_mode':mode,'timezone':zone})
    return result

@router.put('/jobs/{id}/interest')
def interest(id:str,body:Interest,user=Depends(owner)):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT * FROM entities WHERE user_id=? AND id=? AND kind='job'",(user,id)).fetchone()
        if not row:raise HTTPException(404,'Posting not found.')
        data=json.loads(row['payload']);data.update(interest_state=body.state,interest_updated_at=db.now())
        c.execute('UPDATE entities SET payload=?,updated_at=? WHERE user_id=? AND id=?',(json.dumps(data),db.now(),user,id))
    return db.get(user,id,'job')

# Compatibility endpoints deliberately authenticate before returning retirement status.
@router.api_route('/schedule',methods=['GET','PUT','POST','DELETE'])
@router.post('/check-now')
@router.get('/notifications')
@router.get('/push-key')
@router.api_route('/push',methods=['POST','DELETE'])
@router.post('/email/verify')
@router.post('/email/confirm')
def retired_alerts(user=Depends(auth.current)):
    raise HTTPException(410,'Daily alerts have been retired. Use Job Search for manual searches.')

def restore_record(user,kind,data):
    if kind=='job_search_preferences':return save_preferences(user,Preferences.model_validate(data).model_dump(exclude={'account_id'},exclude_none=True))
    if kind=='job_alert':
        with db.connect() as c:c.execute('DELETE FROM cc_job_email_verifications WHERE user_id=?',(user,))
        return save(user,kind,Schedule.model_validate({**data,'enabled':False,'email_enabled':False,'browser':False}).model_dump())
    return None
