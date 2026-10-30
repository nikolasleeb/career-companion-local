"""Narrow, authenticated application-assistant operations. No browser control service."""
import hashlib
import json
import re
import secrets
import time
from typing import Literal
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from . import auth, config, db, private_answers, private_profile
from .models import StrictModel

STATES=('disconnected','scanning','filling','advancing','needs_input','paused','ready_for_final_review','stopped','failed')
TERMINAL={'stopped','failed','ready_for_final_review'}
PRIVATE=re.compile(r'veteran|disab|gender|\bsex\b|race|ethnic|clearance|government employ|family|relativ|conflict|citizen|nationalit|hispanic|latino|sponsor|authoriz',re.I)
BOUNDARY=re.compile(r'consent|i agree|i confirm|opt[ -]?in|subscribe|captcha|recaptcha|hcaptcha|signature|attest|certif(?:y|ication of)|under penalty|payment|credit card|password|sign[ -]?in|log[ -]?in|submit application|submit my application',re.I)

def init(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS cc_pairings(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,session_hash TEXT NOT NULL,secret_hash TEXT NOT NULL,label TEXT NOT NULL,code TEXT NOT NULL,status TEXT NOT NULL,expires REAL NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cc_runs(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,pairing_id TEXT NOT NULL REFERENCES cc_pairings(id) ON DELETE CASCADE,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS cc_runs_owner ON cc_runs(user_id);
    CREATE TABLE IF NOT EXISTS cc_run_answers(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,run_id TEXT NOT NULL REFERENCES cc_runs(id) ON DELETE CASCADE,ciphertext TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cc_ai_requests(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,run_id TEXT NOT NULL REFERENCES cc_runs(id) ON DELETE CASCADE,request_hash TEXT NOT NULL,state TEXT NOT NULL,reserved REAL NOT NULL,actual REAL,day TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(user_id,id));
    ''')
    # Restart recovery never dispatches again or resumes a browser automatically.
    for row in c.execute('SELECT * FROM cc_runs').fetchall():
        value=json.loads(row['payload'])
        if value['state'] in ('scanning','filling','advancing'):
            value.update(state='paused',reason='Server restarted. Reactivate the extension to continue.',version=value['version']+1)
            c.execute('UPDATE cc_runs SET payload=? WHERE id=?',(json.dumps(value),row['id']))
    c.execute("UPDATE cc_ai_requests SET state='unknown' WHERE state IN ('dispatching','cancelling')")
    c.execute('DELETE FROM cc_run_answers')

def origin(value):
    try:
        p=urlsplit(value)
        local=p.hostname in ('localhost','127.0.0.1','::1')
        if p.scheme not in ('https','http') or (p.scheme=='http' and not local) or p.username or p.password or not p.hostname or p.path not in ('','/') or p.query or p.fragment:raise ValueError()
        _=p.port
        return f'{p.scheme}://{p.netloc}'.rstrip('/')
    except ValueError:raise ValueError('Use an exact HTTPS website origin; HTTP is only allowed for localhost fixtures.') from None

class PairRequest(StrictModel):
    secret: str = Field(min_length=43,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    label: Literal['Chrome on this computer','Safari on this computer','Extension test fixture']
class PairApproval(StrictModel):
    code: str = Field(min_length=6,max_length=6)
class Relay(StrictModel):
    pairing_id: str = Field(min_length=32,max_length=32)
    secret: str = Field(min_length=43,max_length=100)
class CreateRun(Relay):
    protocol_version: Literal[1,2] = 1
    application_id: str = Field(max_length=64)
    allowed_origin: str = Field(max_length=2000)
    tab_id: int = Field(ge=0)
    resume_id: str = Field(max_length=64)
    cover_letter_id: str = Field(default='',max_length=64)
    documents_approved: Literal[True]
    document_versions: dict[str,str] | None = None
    @field_validator('allowed_origin')
    @classmethod
    def valid_origin(cls,v):return origin(v)
class FieldInfo(StrictModel):
    id: str = Field(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9_-]+$')
    label: str = Field(max_length=500)
    description: str = Field(default='',max_length=1500)
    context: str = Field(default='',max_length=1000)
    control: Literal['text','email','tel','url','number','date','textarea','select','radio','checkbox','combobox','file','unsupported']
    autocomplete: str = Field(default='',max_length=100)
    options: list[str] = Field(default_factory=list,max_length=private_answers.MAX_OPTIONS)
    has_value: bool = False
    required: bool = False
    section: Literal['','education','employment'] = ''
    repeat_index: int = Field(default=0,ge=0,le=30)
    @field_validator('options')
    @classmethod
    def valid_options(cls,v):
        if any(len(x)>500 for x in v):raise ValueError('Choice too long.')
        return v
class ScanMetadata(StrictModel):
    version: Literal[2]
    manual_fields: list[str] = Field(default_factory=list,max_length=120)

class Scan(Relay):
    expected_version: int = Field(ge=1)
    origin: str = Field(max_length=2000)
    tab_id: int = Field(ge=0)
    signature: str = Field(min_length=32,max_length=64,pattern=r'^[a-f0-9]+$')
    fields: list[FieldInfo] = Field(max_length=120)
    boundaries: list[Literal['login','captcha','signature','attestation','payment','inaccessible_frame','unsupported_control']] = Field(default_factory=list,max_length=7)
    final_review: bool = False
    metadata: ScanMetadata | None = None
class Progress(Relay):
    expected_version: int
    origin: str = Field(max_length=2000)
    tab_id: int = Field(ge=0)
    state: Literal['filling','advancing','needs_input','paused','ready_for_final_review','stopped','failed']
    write_ids: list[str] = Field(default_factory=list,max_length=120)
    failed_ids: list[str] = Field(default_factory=list,max_length=120)
    reason: Literal['','manual_handoff','conflict','validation','stalled_navigation','unsupported_control','boundary','user_action','final_review','connection_lost'] = ''
class Reactivation(Relay):
    tab_id: int = Field(ge=0)
    origin: str = Field(max_length=2000)

class Control(StrictModel):
    activation: Reactivation | None = None
    protocol_version: Literal[2] | None = None
    action: Literal['pause','stop','resume']
    expected_version: int
class ReviewedAnswer(StrictModel):
    question_id: str = Field(max_length=100)
    value: str = Field(min_length=1,max_length=3000)
    answer_kind: Literal['private','professional'] = 'private'
    experience_ids:list[str]=Field(default_factory=list,max_length=10)
    decision: Literal['once','save']
    private_answer: private_answers.Answer | None = None
    expected_version: int

def session_hash(user):return auth.digest(user['csrf'])
def paired(user,body):
    with db.connect() as c:
        row=c.execute('SELECT * FROM cc_pairings WHERE id=? AND user_id=?',(body.pairing_id,user['id'])).fetchone()
    if not row or row['status']!='approved' or row['expires']<=time.time() or row['session_hash']!=session_hash(user) or not secrets.compare_digest(row['secret_hash'],auth.digest(body.secret)):
        raise HTTPException(403,'Connection expired or revoked. Pair again in the signed-in app.')
    return row

def load(user,id):
    with db.connect() as c:row=c.execute('SELECT payload FROM cc_runs WHERE id=? AND user_id=?',(id,user)).fetchone()
    if not row:raise HTTPException(404,'Assistant run not found.')
    return json.loads(row['payload'])

def persist(user,run,expected):
    run['version']=expected+1
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT payload FROM cc_runs WHERE id=? AND user_id=?',(run['id'],user)).fetchone()
        if not old or json.loads(old['payload'])['version']!=expected:raise HTTPException(409,'Run changed. Refresh before continuing.')
        c.execute('UPDATE cc_runs SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(run),db.now(),run['id'],user))
        if run['state'] in TERMINAL or run['state']=='paused':c.execute('DELETE FROM cc_run_answers WHERE run_id=? AND user_id=?',(run['id'],user))
    return public(run)

def public(run):return {k:v for k,v in run.items() if k not in ('plan_ids','session_hash')}

def relay_run(user,id,body):
    pair=paired(user,body);run=load(user['id'],id)
    if run['pairing_id']!=pair['id'] or run['session_hash']!=session_hash(user):raise HTTPException(403,'Run belongs to a different connection.')
    if run['expires']<=time.time():raise HTTPException(403,'Run expired. Start a new run.')
    if hasattr(body,'tab_id') and (body.tab_id!=run['tab_id'] or body.origin!=run['allowed_origin']):
        run.update(state='paused',reason='Website origin changed. Renew activation for this website.')
        persist(user['id'],run,run['version']);raise HTTPException(403,'Website origin or tab changed. Renew activation.')
    return run

def owned(user,id,kind):
    record=db.get(user,id,kind)
    if not record:raise HTTPException(404,'Selected record not found.')
    return record

def check_documents(user,run):
    for selection in run['documents']:
        record=owned(user,selection['id'],selection['kind'])
        if record['updated_at']!=selection['updated_at']:raise HTTPException(409,'Document changed. Stop this run and approve the new document version before starting again.')

def revoke_session(user,csrf=None):
    with db.connect() as c:
        sql="UPDATE cc_pairings SET status='revoked' WHERE user_id=?"
        args=[user]
        if csrf:sql+=' AND session_hash=?';args.append(auth.digest(csrf))
        c.execute(sql,args)
        for row in c.execute('SELECT payload FROM cc_runs WHERE user_id=?',(user,)).fetchall():
            run=json.loads(row['payload'])
            if csrf and run['session_hash']!=auth.digest(csrf):continue
            if run['state'] not in TERMINAL:
                run.update(state='stopped',reason='Account session ended.',version=run['version']+1)
                c.execute('UPDATE cc_runs SET payload=? WHERE id=?',(json.dumps(run),run['id']))
        c.execute('DELETE FROM cc_run_answers WHERE user_id=?',(user,))

def local_value(user,field,application):
    settings=db.settings(user);label=private_answers.normalized(field.label).strip(' :*')
    if field.control in ('file','unsupported') or BOUNDARY.search(' '.join((field.label,field.description,field.context))):return None
    if private_answers.classify(field.label,field.description,field.context) in private_answers.REVIEW_CATEGORIES|{'family_connection'}:return None
    if field.control=='checkbox':return private_answers.match(user,field.label,field.options,application,field.description,field.context)
    if PRIVATE.search(' '.join((field.label,field.description,field.context))):return private_answers.match(user,field.label,field.options,application,field.description,field.context)
    mapping={'name':'name','full name':'name','email':'email','email address':'email','confirm email':'email','confirm email address':'email','phone':'phone','phone number':'phone','city':'city','state':'state','country':'country','linkedin':'linkedin','linkedin profile':'linkedin','website':'website','portfolio website':'website'}
    auto={'name':'name','email':'email','tel':'phone','address-level2':'city','address-level1':'state','country-name':'country','url':'website'}
    key=('github' if label in ('github','github profile','github url','github profile url','github link','github profile link') else None) if re.search(r'\bgithub\b',label) else auto.get(field.autocomplete) or mapping.get(label)
    value=settings.get(key,'') if key else ''
    if field.section:
        rows=[r['data'] for r in reversed(db.list_entities(user,'experience')) if r['data'].get('confirmed') and r['data'].get('category')==field.section]
        if field.repeat_index<len(rows):
            row=rows[field.repeat_index]
            key=({'school':'organization','school name':'organization','university':'organization','degree':'degree','major':'major','field of study':'major','start date':'start_date','end date':'end_date'} if field.section=='education' else {'employer':'organization','company':'organization','company name':'organization','job title':'title','title':'title','start date':'start_date','end date':'end_date'}).get(label)
            value=row.get(key,'') if key else ''
    if not value:
        for saved in db.list_entities(user,'profile_answer'):
            a=saved['data']
            if a.get('status')=='confirmed' and a.get('answer_kind')=='experience' and not field.options and any(private_answers.normalized(q.get('text',''))==private_answers.normalized(field.label) and private_answers.normalized(q.get('description',''))==private_answers.normalized(field.description) and private_answers.normalized(q.get('context',''))==private_answers.normalized(field.context) for src in a.get('sources',[]) for q in src.get('questions',[])):
                return a.get('text') or None
        return private_answers.match(user,field.label,field.options,application,field.description,field.context)
    if field.options:
        matched=[o for o in field.options if private_answers.normalized(o)==private_answers.normalized(str(value))]
        return matched[0] if len(matched)==1 else None
    return str(value)

router=APIRouter(prefix='/api/application-agent',tags=['Application assistant'])
@router.get('/status')
def status(user=Depends(auth.current)):
    with db.connect() as c:
        pairs=[{k:r[k] for k in ('id','label','code','status','expires')} for r in c.execute('SELECT * FROM cc_pairings WHERE user_id=? AND session_hash=? AND expires>? ORDER BY created_at DESC',(user['id'],session_hash(user),time.time()))]
        runs=[public(json.loads(r['payload'])) for r in c.execute('SELECT payload FROM cc_runs WHERE user_id=? ORDER BY updated_at DESC LIMIT 30',(user['id'],))]
    return {'protocol_version':2,'pairings':pairs,'runs':runs,'states':STATES,'ai_model':'gpt-6-luna','run_budget_usd':0.25,'daily_budget_usd':2,'routine_model_cost_usd':0}
@router.post('/pairings/request')
def request_pair(body:PairRequest,user=Depends(auth.current)):
    auth.throttle(('pair',user['id']));id=db.uid();code=f'{secrets.randbelow(1000000):06d}'
    with db.connect() as c:c.execute('INSERT INTO cc_pairings VALUES(?,?,?,?,?,?,?,?,?)',(id,user['id'],session_hash(user),auth.digest(body.secret),body.label,code,'pending',time.time()+3600,db.now()))
    return {'id':id,'code':code,'status':'pending'}
@router.post('/pairings/{id}/approve')
def approve_pair(id:str,body:PairApproval,user=Depends(auth.current)):
    with db.connect() as c:
        row=c.execute('SELECT * FROM cc_pairings WHERE id=? AND user_id=? AND session_hash=?',(id,user['id'],session_hash(user))).fetchone()
        if not row or row['expires']<=time.time() or row['status']!='pending' or not secrets.compare_digest(row['code'],body.code):raise HTTPException(409,'Pairing code expired or changed.')
        c.execute("UPDATE cc_pairings SET status='approved' WHERE id=?",(id,))
    return {'approved':True}
@router.delete('/pairings/{id}')
def revoke_pair(id:str,user=Depends(auth.current)):
    with db.connect() as c:
        c.execute("UPDATE cc_pairings SET status='revoked' WHERE id=? AND user_id=?",(id,user['id']))
        for row in c.execute('SELECT payload FROM cc_runs WHERE pairing_id=? AND user_id=?',(id,user['id'])).fetchall():
            run=json.loads(row['payload']);run.update(state='stopped',reason='Connection revoked.',version=run['version']+1)
            c.execute('UPDATE cc_runs SET payload=? WHERE id=?',(json.dumps(run),run['id']))
            c.execute('DELETE FROM cc_run_answers WHERE run_id=?',(run['id'],))
    return {'ok':True}
@router.post('/relay/context')
def relay_context(body:Relay,user=Depends(auth.current)):
    paired(user,body)
    return {'protocol_version':2,'account_id':user['id'],'applications':[{'id':a['id'],'title':a['data']['title'],'company':a['data'].get('company',''),'resume_ids':a['data'].get('resume_ids',[]),'cover_letter_ids':[x['record_id'] for x in a['data'].get('attachments',[]) if x['kind']=='cover_letter']} for a in db.list_entities(user['id'],'application')], 'resumes':[{'id':r['id'],'title':r['data'].get('title','Resume'),'updated_at':r['updated_at']} for r in db.list_entities(user['id'],'resume')], 'cover_letters':[{'id':r['id'],'title':r['data'].get('title','Cover letter'),'updated_at':r['updated_at']} for r in db.list_entities(user['id'],'cover_letter')]}
@router.post('/runs')
def create_run(body:CreateRun,user=Depends(auth.current)):
    paired(user,body);application=owned(user['id'],body.application_id,'application')
    if body.resume_id not in application['data'].get('resume_ids',[]):raise HTTPException(422,'Confirm a resume attached to this application.')
    resume=owned(user['id'],body.resume_id,'resume')
    if resume['data'].get('schema_version')==2 and resume['data'].get('layout',{}).get('pages')!=1:raise HTTPException(422,'Select a validated one-page resume version.')
    docs=[{'id':resume['id'],'kind':'resume','updated_at':resume['updated_at']}]
    if body.cover_letter_id:
        if body.cover_letter_id not in [x['record_id'] for x in application['data'].get('attachments',[])]:raise HTTPException(422,'Confirm a cover letter attached to this application.')
        letter=owned(user['id'],body.cover_letter_id,'cover_letter')
        if letter['data'].get('resume_id')!=resume['id']:raise HTTPException(422,'Cover letter belongs to a different resume version.')
        docs.append({'id':letter['id'],'kind':'cover_letter','updated_at':letter['updated_at']})
    if body.document_versions is not None and body.document_versions!={d['id']:d['updated_at'] for d in docs}:raise HTTPException(409,'Document versions changed. Review and approve the exact versions again.')
    id=db.uid();run={'id':id,'protocol_version':body.protocol_version,'application_id':application['id'],'account_id':user['id'],'pairing_id':body.pairing_id,'session_hash':session_hash(user),'tab_id':body.tab_id,'allowed_origin':body.allowed_origin,'documents':docs,'state':'scanning','reason':'','version':1,'pages':0,'writes':0,'signatures':[],'plan_ids':[],'unresolved':[],'activity':[],'expires':time.time()+3600}
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for previous in c.execute('SELECT payload FROM cc_runs WHERE user_id=?',(user['id'],)):
            old=json.loads(previous['payload'])
            if old['state'] not in TERMINAL and old['expires']>time.time():raise HTTPException(409,'Stop the current run before starting another.')
        c.execute('INSERT INTO cc_runs VALUES(?,?,?,?,?)',(id,user['id'],body.pairing_id,json.dumps(run),db.now()))
    return public(run)
@router.get('/runs/{id}')
def run_status(id:str,user=Depends(auth.current)):
    run=load(user['id'],id)
    if run['expires']<=time.time() and run['state'] not in TERMINAL:
        run.update(state='stopped',reason='Run expired. Start a new activation.')
        return persist(user['id'],run,run['version'])
    return public(run)
@router.post('/runs/{id}/relay-status')
def relay_status(id:str,body:Relay,user=Depends(auth.current)):
    return public(relay_run(user,id,body))
@router.post('/runs/{id}/scan')
def scan(id:str,body:Scan,user=Depends(auth.current)):
    run=relay_run(user,id,body)
    if run['version']!=body.expected_version:raise HTTPException(409,'Run changed. Refresh before scanning.')
    if run['state'] in TERMINAL or run['state']=='paused':raise HTTPException(409,'Reactivate or start a run before scanning.')
    if len({f.id for f in body.fields})!=len(body.fields):raise HTTPException(422,'Duplicate field IDs.')
    check_documents(user['id'],run)
    run['activity']=(run['activity']+[{'event':'scan','at':db.now(),'field_count':len(body.fields)}])[-100:]
    manual=set(body.metadata.manual_fields) if body.metadata else set()
    if manual-{f.id for f in body.fields}:raise HTTPException(422,'Manual handoff references an unknown field.')
    hard=re.compile(r'captcha|payment|credit card|password|sign[ -]?in|log[ -]?in',re.I)
    blocked=bool(body.boundaries) or any((hard if body.metadata else BOUNDARY).search(' '.join((f.label,f.description,f.context))) for f in body.fields)
    if blocked:
        run.update(state='needs_input',reason='A login, verification, attestation, signature, payment, frame or unsupported control requires your action.',plan_ids=[])
        return {'run':persist(user['id'],run,body.expected_version),'writes':[]}
    if body.final_review and not body.fields:
        run.update(state='ready_for_final_review',reason='Review and submit personally.',plan_ids=[])
        return {'run':persist(user['id'],run,body.expected_version),'writes':[]}
    if run['pages']>=20 or run['writes']>=300 or body.signature in run['signatures']:
        run.update(state='paused',reason='Page limit, repeated page or stalled navigation. Review the form personally.',plan_ids=[])
        return {'run':persist(user['id'],run,body.expected_version),'writes':[]}
    run['pages']+=1;run['signatures'].append(body.signature);run['unresolved']=[];writes=[]
    application=owned(user['id'],run['application_id'],'application')
    with db.connect() as c:once={r['id']:private_answers.unseal(user['id'],r['id'],r['ciphertext']) for r in c.execute('SELECT * FROM cc_run_answers WHERE user_id=? AND run_id=?',(user['id'],id))}
    for f in body.fields:
        protected=bool(BOUNDARY.search(' '.join((f.label,f.description,f.context))))
        if f.has_value:continue
        if f.id in manual or protected:
            run['unresolved'].append({'id':f.id,'label':f.label,'description':f.description,'context':f.context,'options':[],'control':f.control,'required':f.required,'private':bool(PRIVATE.search(f.label)),'reason':'manual_handoff','manual_only':True})
            continue
        category=private_answers.category_for(user['id'],f.label,f.description,f.context)
        saved=next((v['value'] for v in once.values() if v['question']==f.label and v['options']==f.options and v.get('description','')==f.description and v.get('context','')==f.context),None)
        value=None if category=='family_connection' else saved or (None if category in private_answers.REVIEW_CATEGORIES else local_value(user['id'],f,application))
        if value is None or f.control in ('file','unsupported'):
            run['unresolved'].append({'id':f.id,'label':f.label,'description':f.description,'context':f.context,'options':f.options,'control':f.control,'required':f.required,'private':bool(category or PRIVATE.search(' '.join((f.label,f.description,f.context)))),'private_category':category,'reason':'family_connection_manual' if category=='family_connection' else 'manual_handoff' if f.control=='file' else 'review_required'})
        elif run['writes']+len(writes)<300:writes.append({'id':f.id,'value':value})
    run['plan_ids']=[w['id'] for w in writes]
    run.update(state='filling' if writes else 'needs_input' if run['unresolved'] else 'advancing',reason='Review unresolved questions in Career Companion.' if run['unresolved'] else '')
    return {'run':persist(user['id'],run,body.expected_version),'writes':writes}
@router.get('/runs/{id}/questions/{question_id}/suggestions')
def question_suggestions(id:str,question_id:str,user=Depends(auth.current)):
    run=load(user['id'],id)
    if run['session_hash']!=session_hash(user) or run['expires']<=time.time() or run['state'] in TERMINAL:raise HTTPException(403,'Run is not available for review.')
    q=next((q for q in run['unresolved'] if q['id']==question_id),None)
    if not q:raise HTTPException(404,'Unresolved question not found.')
    result=private_profile.suggestions(user['id'],q,owned(user['id'],run['application_id'],'application'))
    return {**result,'run_version':run['version']}

@router.post('/runs/{id}/progress')
def progress(id:str,body:Progress,user=Depends(auth.current)):
    run=relay_run(user,id,body)
    if run['version']!=body.expected_version:raise HTTPException(409,'Run changed. Refresh before reporting progress.')
    if run['state'] in TERMINAL or run['state']=='paused':raise HTTPException(409,'Run is stopped or paused.')
    if set(body.write_ids+body.failed_ids)-set(run['plan_ids']) or len(set(body.write_ids))!=len(body.write_ids):raise HTTPException(422,'Progress does not match the approved write plan.')
    if len(set(body.failed_ids))!=len(body.failed_ids) or set(body.write_ids)&set(body.failed_ids):raise HTTPException(422,'Duplicate progress IDs.')
    run['writes']+=len(body.write_ids)
    completed=set(body.write_ids+body.failed_ids)
    run['plan_ids']=[i for i in run['plan_ids'] if i not in completed] if body.state=='filling' else []
    if run['writes']>300:raise HTTPException(422,'Write limit exceeded.')
    run.update(state=body.state,reason=body.reason)
    if body.failed_ids:run.update(state='needs_input',reason='Some fields did not pass readback or validation. Review them personally.')
    run['activity']=(run['activity']+[{'event':run['state'],'at':db.now(),'write_count':len(body.write_ids),'failed_count':len(body.failed_ids)}])[-100:]
    return persist(user['id'],run,body.expected_version)
@router.post('/runs/{id}/control')
def control(id:str,body:Control,user=Depends(auth.current)):
    run=load(user['id'],id)
    if run['state'] in TERMINAL:raise HTTPException(409,'This run has ended. Start a new run.')
    if body.action=='resume':
        if run['expires']<=time.time() or run['session_hash']!=session_hash(user):raise HTTPException(403,'Run session expired. Review it in Career Companion and start a new activation.')
        check_documents(user['id'],run)
        if body.activation:
            pair=paired(user,body.activation)
            if run['state']!='paused' or body.activation.tab_id!=run['tab_id'] or body.activation.origin!=run['allowed_origin']:raise HTTPException(403,'Recovery requires the original employer tab and website, with this run paused.')
            run['pairing_id']=pair['id']
    if body.action=='resume' and run['state'] not in ('paused','needs_input'):raise HTTPException(409,'Pause or review this run before resuming.')
    run.update(state={'pause':'paused','stop':'stopped','resume':'scanning'}[body.action],reason='User requested '+body.action,plan_ids=[])
    # Resume is explicit and rescans the current page after reviewed answers.
    if body.action=='resume':
        run['signatures']=[]
        if body.protocol_version:run['protocol_version']=body.protocol_version
    return persist(user['id'],run,body.expected_version)
@router.post('/runs/{id}/answers')
def review_answer(id:str,body:ReviewedAnswer,user=Depends(auth.current)):
    run=load(user['id'],id)
    if run['state'] not in ('needs_input','filling'):raise HTTPException(409,'This run is not awaiting an answer.')
    if run['version']!=body.expected_version:raise HTTPException(409,'Run changed. Refresh before reviewing.')
    q=next((q for q in run['unresolved'] if q['id']==body.question_id),None)
    if not q or q.get('manual_only') or q['control'] in ('file','unsupported'):raise HTTPException(422,'Use the browser for this manual handoff.')
    category=q.get('private_category') or private_answers.category_for(user['id'],q['label'],q.get('description',''),q.get('context',''))
    if category=='family_connection':raise HTTPException(422,'Complete this employer family-connection question manually on the employer website.')
    if category in private_answers.REVIEW_CATEGORIES and (body.decision!='once' or body.answer_kind!='private'):raise HTTPException(422,'Review this private answer for this run only; manage defaults in your private profile.')
    if q['options'] and body.value not in q['options']:raise HTTPException(422,'Choose an exact available option.')
    if body.decision=='save' and body.answer_kind=='professional':
        if q['private'] or PRIVATE.search(body.value):raise HTTPException(422,'Private disclosures must remain in the encrypted vault.')
        from . import profile_answers
        profile_answers.confirm_application_answer(user['id'],owned(user['id'],run['application_id'],'application'),q['label'],body.value,q.get('description',''),q.get('context',''),body.experience_ids)
    elif body.decision=='save':
        a=body.private_answer
        if not a or a.question!=q['label'] or a.options!=q['options'] or a.description!=q.get('description','') or a.context!=q.get('context','') or a.value!=body.value:raise HTTPException(422,'Review the exact question, choices and scope before saving.')
        private_answers.save(user['id'],a)
    answer_id=db.uid();ciphertext=private_answers.seal(user['id'],answer_id,{'question':q['label'],'options':q['options'],'description':q.get('description',''),'context':q.get('context',''),'value':body.value})
    with db.connect() as c:c.execute('INSERT INTO cc_run_answers VALUES(?,?,?,?)',(answer_id,user['id'],id,ciphertext))
    run['unresolved']=[x for x in run['unresolved'] if x['id']!=q['id']]
    return persist(user['id'],run,body.expected_version)
@router.get('/runs/{id}/documents/{document_id}')
def approved_document(id:str,document_id:str,user=Depends(auth.current)):
    from . import documents,cover_letters
    from fastapi import Response
    run=load(user['id'],id)
    if run['expires']<=time.time() or run['state'] in ('stopped','failed'):raise HTTPException(403,'Document disclosure approval expired.')
    selection=next((d for d in run['documents'] if d['id']==document_id),None)
    if not selection:raise HTTPException(403,'This document was not approved for this run.')
    record=owned(user['id'],document_id,selection['kind'])
    if record['updated_at']!=selection['updated_at']:raise HTTPException(409,'Document changed. Confirm the new version in a new run.')
    if record['kind']=='resume' and record['data'].get('origin')=='uploaded':
        from .application_documents import uploaded_original,response_file
        document,raw=uploaded_original(user['id'],record)
        return response_file(raw,document['data']['filename'],document['data']['mime'])
    if record['kind']=='resume':raw,mime=documents.export_resume(record['data'],'pdf')
    else:raw,mime=cover_letters.export_data(record['data'],'pdf')
    return Response(raw,media_type=mime,headers={'Content-Disposition':f'attachment; filename="career-companion-{record["kind"]}-{document_id[:8]}.pdf"','Cache-Control':'private, no-store'})
