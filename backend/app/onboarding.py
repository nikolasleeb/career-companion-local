"""Account-owned, resumable Profile setup; reviewed evidence unlocks application tools."""
import hashlib
import json
import re
from fastapi import HTTPException
from . import db
from .models import StrictModel
from pydantic import Field
from typing import Literal

SECTIONS=('education','employment','project','volunteering','skills','coursework')
TITLES=dict(zip(SECTIONS,('Education','Employment','Projects','Volunteering','Skills','Coursework')))
LEGACY=('application','resume','cover_letter','resume_draft','resume_revision','cover_revision')
LOCK_MESSAGE='Complete Profile setup first. Review your master-resume checklist in Profile.'

class Decision(StrictModel):
    expected_version:int=Field(ge=1)
    profile_signature:str=Field(min_length=64,max_length=64)
    section:Literal['employment','project','volunteering','skills','coursework']
    empty:bool
class Finish(StrictModel):
    expected_version:int=Field(ge=1)
    profile_signature:str=Field(min_length=64,max_length=64)

def identity(user):return hashlib.sha256((user+':onboarding-v1').encode()).hexdigest()[:32]
def restricted(path):
    return bool(re.match(r'^/api/(?:jobs|analyses|resumes|resume-content|resume-conversations|resume-revisions|resume-drafts|cover-letters|cover-workspaces|cover-revisions|applications|preparation|interviews|boards|demo)(?:/|$)',path))
def _write(c,user,data):
    stamp=db.now();key=identity(user)
    c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',(key,user,'onboarding',json.dumps(data),stamp,stamp))
def _ensure(c,user):
    row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='onboarding'",(identity(user),user)).fetchone()
    if row:return json.loads(row[0])
    legacy=c.execute("SELECT 1 FROM entities WHERE user_id=? AND kind IN ("+','.join('?' for _ in LEGACY)+") LIMIT 1",(user,*LEGACY)).fetchone()
    data={'schema_version':1,'version':1,'empty_sections':[],'completed_at':db.now() if legacy else '', 'grandfathered':bool(legacy)}
    _write(c,user,data);return data

def profile_added(c,user,kind,value):
    # Used by both ordinary writes and transactional approval/import writes.
    if kind not in ('experience','profile_answer','answer_draft'):return
    if kind=='profile_answer' and (value.get('status')!='confirmed' or value.get('answer_kind')!='experience'):return
    if kind=='answer_draft' and (value.get('builder')!='project' or value.get('status')!='draft'):return
    category=value.get('category','project')
    if value.get('experience_id'):
        row=c.execute("SELECT payload FROM entities WHERE user_id=? AND id=? AND kind='experience'",(user,value['experience_id'])).fetchone()
        if row:category=json.loads(row[0]).get('category',category)
    changed={category}
    if kind=='experience' and category=='education' and value.get('relevant_courses','').strip():changed.add('coursework')
    row=c.execute("SELECT payload FROM entities WHERE id=? AND user_id=? AND kind='onboarding'",(identity(user),user)).fetchone()
    if not row:return
    data=json.loads(row[0]);empty=[s for s in data['empty_sections'] if s not in changed]
    if empty!=data['empty_sections']:data.update(empty_sections=empty,version=data['version']+1);_write(c,user,data)

def _profile(c,user):
    rows=[db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind IN ('experience','profile_answer','answer_draft') ORDER BY id",(user,))]
    records={r['id']:r['data'] for r in rows if r['kind']=='experience'}
    groups={s:[] for s in SECTIONS};pending={s:0 for s in SECTIONS}
    for data in records.values():
        category=data.get('category')
        if category not in groups:continue
        if data.get('confirmed'):
            groups[category].append(data)
            if category=='education' and data.get('relevant_courses','').strip():groups['coursework'].append(data)
        else:pending[category]+=1
    for row in rows:
        d=row['data']
        if row['kind']=='profile_answer' and d.get('status')=='confirmed' and d.get('answer_kind')=='experience':
            target=records.get(d.get('experience_id'))
            if target:continue # Already counted via the linked master record.
            if d.get('backed_fields'):continue # A missing linked record cannot establish evidence.
            category=d.get('category','project')
            if category in groups and d.get('text','').strip():groups[category].append(d)
        if row['kind']=='answer_draft' and d.get('builder')=='project' and d.get('status')=='draft':
            category=records.get(d.get('experience_id'),{}).get('category','project')
            if category in pending:pending[category]+=1
    signature=hashlib.sha256(json.dumps([(r['id'],r['kind'],r['data']) for r in rows],sort_keys=True).encode()).hexdigest()
    return groups,pending,signature

def _state(c,user,data):
    groups,pending,signature=_profile(c,user)
    # An empty-section acknowledgement expires whenever information is added.
    empty=[s for s in data['empty_sections'] if not groups[s] and not pending[s]]
    if empty!=data['empty_sections']:
        data.update(empty_sections=empty,version=data['version']+1);_write(c,user,data)
    education=any(d.get('organization','').strip() and (d.get('degree','').strip() or (d.get('title','').strip().casefold() not in ('','education',d.get('organization','').strip().casefold()))) for d in groups['education'] if d.get('category')=='education')
    sections=[]
    for s in SECTIONS:
        ready=bool(groups[s]) and (s!='education' or education)
        status='needs_review' if pending[s] else 'complete' if ready else 'empty' if s in empty else 'required' if s=='education' else 'not_started'
        sections.append({'id':s,'title':TITLES[s],'status':status,'confirmed_count':len(groups[s]),'draft_count':pending[s],'can_mark_empty':s!='education' and not groups[s] and not pending[s]})
    return {**data,'id':identity(user),'profile_signature':signature,'sections':sections,'completed':bool(data['completed_at']),'ready':all(s['status'] in ('complete','empty') for s in sections)}

def status(user):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        return _state(c,user,_ensure(c,user))

def migrate():
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for r in c.execute('SELECT id FROM users').fetchall():_ensure(c,r[0])

def require_complete(user):
    if not status(user)['completed']:raise HTTPException(403,LOCK_MESSAGE,headers={'X-Next-Step-Setup':'required'})

def update(user,body,finish=False):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');data=_ensure(c,user);state=_state(c,user,data)
        if finish and data['completed_at']:return state
        if data['version']!=body.expected_version or state['profile_signature']!=body.profile_signature:raise HTTPException(409,'Your Profile or setup checklist changed. Reload the checklist and review its current information.')
        if finish:
            if data['completed_at']:return state
            if not state['ready']:raise HTTPException(409,'Review every section and add confirmed education before finishing setup.')
            data.update(completed_at=db.now(),grandfathered=False)
        else:
            section=next(s for s in state['sections'] if s['id']==body.section)
            if body.empty and not section['can_mark_empty']:raise HTTPException(409,'Review or remove the information in this section before marking it empty.')
            data['empty_sections']=[s for s in data['empty_sections'] if s!=body.section]+([body.section] if body.empty else [])
        data['version']+=1;_write(c,user,data)
        return _state(c,user,data)

def validate_backup(data):
    if data.get('schema_version')!=1 or type(data.get('version'))!=int or data['version']<1:raise ValueError()
    empty=data.get('empty_sections')
    if not isinstance(empty,list) or len(empty)!=len(set(empty)) or set(empty)-set(SECTIONS[1:]):raise ValueError()
    if not isinstance(data.get('completed_at'),str) or type(data.get('grandfathered'))!=bool:raise ValueError()
    if data['completed_at']:
        from datetime import datetime
        datetime.fromisoformat(data['completed_at'])

def restore(user,incoming,legacy=False):
    """Merge into the one canonical record; never relock an established account."""
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');data=_ensure(c,user)
        if incoming:
            data['empty_sections']=list(dict.fromkeys(data['empty_sections']+incoming['empty_sections']))
            if incoming['completed_at'] and not data['completed_at']:data.update(completed_at=incoming['completed_at'],grandfathered=incoming['grandfathered'])
        elif legacy and not data['completed_at']:data.update(completed_at=db.now(),grandfathered=True)
        data['version']+=1;_write(c,user,data);return _state(c,user,data)
