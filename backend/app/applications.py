"""Account-owned application history and count-conserving dashboard paths."""
import hashlib
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from . import db, resume_data
from .network import ServiceError

LOCK = threading.RLock()
STAGES = ['preparing','applied','screening','interviewing','offer','accepted','rejected','withdrawn','declined']
PROGRESS = ['applied','screening','interviewing','offer','accepted']
CLOSED = {'accepted','rejected','withdrawn','declined'}

def public(record):
    if not record: return None
    data={k:v for k,v in record['data'].items() if k!='artifacts'}
    if record['kind']=='resume' and data.get('origin')!='uploaded':data['title']=resume_data.resume_title(data.get('posting_snapshot'),data.get('title') or 'Resume',data.get('name') or '')
    return {**record,'data':data}

def attach_resume(user, resume):
    data=resume['data']; job_id=data.get('job_id')
    if not job_id and data.get('analysis_id'):
        analysis=db.get(user,data['analysis_id'],'analysis')
        job_id=analysis['data'].get('job_id') if analysis else None
    if not job_id: return
    job=db.get(user,job_id,'job')
    analysis=db.get(user,data.get('analysis_id',''),'analysis')
    snapshot=data.get('posting_snapshot') or (analysis['data'].get('posting_snapshot') if analysis else None) or (job['data'] if job else {})
    if not snapshot: return
    with LOCK:
        existing=next((r for r in db.list_entities(user,'application') if r['data'].get('job_id')==job_id),None)
        if existing:
            updated=dict(existing['data'])
            updated['resume_ids']=list(dict.fromkeys(updated.get('resume_ids',[])+[resume['id']]))
            if resume['id'] not in existing['data'].get('resume_ids',[]) and not existing['data'].get('workflow',{}).get('resume_id') and not existing['data'].get('submitted_resume_id'):
                updated['workflow']={'step':'resume','resume_id':resume['id'],'cover_letter_id':'','cover_skipped':False}
            if updated!=existing['data']:db.save(user,'application',updated,existing['id'])
        else:
            entity_id=hashlib.sha256((user+':application:'+job_id).encode()).hexdigest()[:32]
            db.save(user,'application',{'job_id':job_id,'posting_snapshot':snapshot,'title':snapshot.get('title','Opportunity'),'company':snapshot.get('company',''),'url':snapshot.get('url',''),'resume_ids':[resume['id']],'submitted_resume_id':'','status':'preparing','applied_date':'','history':[],'interviews':[],'notes':'','archived':False,'attachments':[],'workflow':{'step':'resume','resume_id':resume['id'],'cover_letter_id':'','cover_skipped':False}},entity_id)

def migrate(user):
    with LOCK:
        if db.settings(user).get('applications_migrated'): return
        for resume in reversed(db.list_entities(user,'resume')): attach_resume(user,resume)
        db.update_settings(user,{'applications_migrated':True})

def validate_links(user, data):
    if data.get('workflow'):validate_workflow(user,data,data['workflow'])
    if data.get('job_id') and not db.get(user,data['job_id'],'job'): raise ServiceError('Choose one of your saved postings.')
    for entity_id in data.get('resume_ids',[]):
        if not db.get(user,entity_id,'resume'): raise ServiceError('Choose only your own saved resume versions.')
    if data.get('submitted_resume_id') and data['submitted_resume_id'] not in data.get('resume_ids',[]): raise ServiceError('The submitted resume must be one of the versions attached to this application.')
    if len({a['record_id'] for a in data.get('attachments',[])})!=len(data.get('attachments',[])):raise ServiceError('Attach each document only once.')
    for attachment in data.get('attachments',[]):
        if attachment['kind']=='document':
            document=db.get(user,attachment['record_id'],'document')
            if not document or document['data'].get('purpose')!='application':raise ServiceError('Choose only your own application documents.')
            owner=db.get(user,document['data'].get('application_id',''),'application')
            if not owner or owner['data'].get('job_id')!=data.get('job_id') or not any(a.get('kind')=='document' and a['record_id']==document['id'] for a in owner['data'].get('attachments',[])):raise ServiceError('Keep each uploaded file with its original application.')
            continue
        letter=db.get(user,attachment['record_id'],'cover_letter')
        if not letter:raise ServiceError('Choose only your own saved cover letters.')
        if letter['data']['job_id']!=data.get('job_id') or letter['data']['resume_id'] not in data.get('resume_ids',[]):raise ServiceError('A cover letter must match this posting and one of its attached resume versions.')
    if data.get('url'):
        from .models import validate_link
        try: validate_link(data['url'])
        except ValueError: raise ServiceError('Enter a complete public HTTP(S) link without credentials.') from None

def path_for(data):
    # Each application follows one forward path, not one path per interview/event.
    events=data.get('history',[])
    seen={e['status'] for e in events}
    status=data.get('status','preparing')
    if status=='preparing': return []
    seen.add(status)
    if data.get('interviews'): seen.add('interviewing')
    path=['applied']+[stage for stage in PROGRESS[1:] if stage in seen]
    if status in ('rejected','withdrawn','declined'): path.append(status)
    elif status!='accepted': path.append('waiting_'+path[-1])
    return path

def chart_date(record,zone):
    """An application date is factual; date-added is a labeled, read-only fallback."""
    value=record['data'].get('applied_date','')
    if value:return value,'applied'
    try:
        added=datetime.fromisoformat(record.get('created_at','').replace('Z','+00:00'))
        if added.tzinfo is None:added=added.replace(tzinfo=timezone.utc)
        return added.astimezone(zone).date().isoformat(),'added'
    except (ValueError,TypeError):return '','unknown'


def dashboard(records, start='', end='', period='week', timezone_name='UTC', include_archived=False):
    # Retain the legacy argument for clients, but archives never enter chart cohorts.
    visible=[r for r in records if not r['data'].get('archived')]
    counts=Counter()
    for r in visible:
        s=r['data']['status']; counts['preparing' if s=='preparing' else 'submitted']+=1
        if s not in CLOSED and s!='preparing': counts['active']+=1
        if s=='interviewing': counts['interviewing']+=1
        if s in ('offer','accepted'): counts['offers']+=1
        if s in CLOSED: counts['closed']+=1
    zone=ZoneInfo(timezone_name);included=[];missing=[];dates={}
    for r in visible:
        d,source=chart_date(r,zone)
        if not d:missing.append(r['id']);continue
        if (not start or d>=start) and (not end or d<=end):
            included.append(r);dates[r['id']]={'date':d,'source':source}
    edges=Counter();nodes=Counter();buckets=Counter();paths={}
    for r in included:
        p=['preparing'] if r['data']['status']=='preparing' else path_for(r['data']);paths[r['id']]=p
        for node in p:nodes[node]+=1
        for a,b in zip(p,p[1:]):edges[(a,b)]+=1
        d=date.fromisoformat(dates[r['id']]['date'])
        key=d.replace(day=1) if period=='month' else d-timedelta(days=d.weekday())
        buckets[key.isoformat()]+=1
    # A bounded complete series includes empty weeks/months. Each application
    # appears once, irrespective of the number of status changes or interviews.
    if start and end:
        first=date.fromisoformat(start);last=date.fromisoformat(end)
        if not 0<=(last-first).days<=365:raise ServiceError('Choose a chart range of up to one year (366 days).')
        cursor=first.replace(day=1) if period=='month' else first-timedelta(days=first.weekday())
        while cursor<=last:
            buckets.setdefault(cursor.isoformat(),0)
            cursor=(date(cursor.year+1,1,1) if cursor.month==12 else date(cursor.year,cursor.month+1,1)) if period=='month' else cursor+timedelta(days=7)
    added_ids=[id for id,d in dates.items() if d['source']=='added']
    return {'counts':{k:counts[k] for k in ('preparing','submitted','active','interviewing','offers','closed')},'cohort_count':len(included),'applied_date_count':len(included)-len(added_ids),'added_date_ids':added_ids,'undated_ids':[r['id'] for r in visible if r['data']['status']!='preparing' and not r['data'].get('applied_date')],'missing_date_ids':missing,'chart_dates':dates,'paths':paths,'nodes':[{'id':k,'count':v} for k,v in nodes.items()],'links':[{'source':a,'target':b,'value':v} for (a,b),v in edges.items()],'submissions':[{'date':k,'count':v} for k,v in sorted(buckets.items())]}


def start(user,job_id):
    """Explicitly starting a saved posting creates Preparing; never Applied."""
    from fastapi import HTTPException
    from .resume_conversation import write
    job=db.get(user,job_id,'job')
    if not job:raise HTTPException(404,'Saved posting not found.')
    with LOCK,db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='application'",(user,)) if __import__('json').loads(r['payload']).get('job_id')==job_id or (job['data'].get('url') and __import__('app.integrations',fromlist=['posting_key']).posting_key(__import__('json').loads(r['payload']).get('url',''))==__import__('app.integrations',fromlist=['posting_key']).posting_key(job['data']['url']))),None)
        if existing:return existing
        from . import job_cache
        if not job_cache.is_active(user,job_id):raise HTTPException(409,'This posting is expired or closed. Existing application history remains available.')
        data={'job_id':job_id,'posting_snapshot':job['data'],'title':job['data']['title'],'company':job['data'].get('company',''),'url':job['data'].get('url',''),'resume_ids':[],'submitted_resume_id':'','status':'preparing','applied_date':'','history':[],'interviews':[],'notes':'','archived':False,'attachments':[],'workflow':{'step':'resume','resume_id':'','cover_letter_id':'','cover_skipped':False}}
        id=write(c,user,'application',data)
    return db.get(user,id,'application')


def set_workflow(user,id,body):
    from fastapi import HTTPException
    from .resume_conversation import write
    with LOCK,db.connect() as c:
        c.execute('BEGIN IMMEDIATE');record=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='application'",(id,user)).fetchone())
        if not record:raise HTTPException(404,'Application not found.')
        if record['updated_at']!=body.expected_updated_at:raise HTTPException(409,'This application changed in another window. Reload before continuing.')
        value=record['data'];workflow=body.workflow.model_dump()
        validate_workflow(user,value,workflow)
        value['workflow']=workflow;write(c,user,'application',value,id)
    return db.get(user,id,'application')


def validate_workflow(user,data,workflow):
    from .models import ApplicationWorkflow
    workflow=ApplicationWorkflow.model_validate(workflow).model_dump()
    if workflow['resume_id']:
        resume=db.get(user,workflow['resume_id'],'resume')
        linked=resume['data'].get('job_id') if resume else None
        if resume and not linked and resume['data'].get('analysis_id'):
            analysis=db.get(user,resume['data']['analysis_id'],'analysis');linked=(analysis or {}).get('data',{}).get('job_id')
        if not resume or linked!=data.get('job_id') or workflow['resume_id'] not in data.get('resume_ids',[]):raise ServiceError('Choose a saved resume attached to this posting.')
    if workflow['step']!='resume' and not workflow['resume_id']:raise ServiceError('Save and review a resume before continuing to the cover letter.')
    if workflow['cover_letter_id']:
        letter=db.get(user,workflow['cover_letter_id'],'cover_letter')
        if not letter or letter['data']['job_id']!=data.get('job_id') or letter['data']['resume_id']!=workflow['resume_id'] or not any(a['record_id']==letter['id'] for a in data.get('attachments',[])):raise ServiceError('Choose the cover letter saved for this exact resume version.')
    if workflow['step']=='agent' and not (workflow['cover_skipped'] or workflow['cover_letter_id']):raise ServiceError('Save a cover letter or explicitly skip it before continuing.')
    if workflow['cover_skipped'] and workflow['cover_letter_id']:raise ServiceError('Choose a saved cover letter or skip it, rather than both.')


def select_saved_letter(user,letter):
    from .resume_conversation import write
    with LOCK,db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        record=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='application'",(user,)) if __import__('json').loads(r['payload']).get('job_id')==letter['data']['job_id']),None)
        if record:
            record['data']['workflow']={'step':'cover','resume_id':letter['data']['resume_id'],'cover_letter_id':letter['id'],'cover_skipped':False}
            write(c,user,'application',record['data'],record['id'])
