"""Reviewed, reusable applicant stories with account ownership and frozen provenance."""
import copy
import hashlib
import json
import re
from fastapi import HTTPException
from . import db
from .models import ExperienceItem

PRIVATE=r'\b(citizenship|citizen|sponsorship|visa(?: status)?|immigration status|work authori[sz]ation|authori[sz]ed to work|eligible to work|allowed to work|us_citizen|authorized_us|sponsorship_now|sponsorship_future)\b'
def norm(text):return re.sub(r'\s+',' ',str(text)).strip().casefold()
def key(user,origin):return hashlib.sha256((user+':profile-answer:'+origin).encode()).hexdigest()[:32]
def write(c,user,data,id=None,allow_unlinked=False):
    from .resume_conversation import write as store
    if not allow_unlinked and data.get('status')=='confirmed' and data.get('answer_kind')=='experience':
        links=validate_links(c,user,experience_ids(data));require_links(links)
    return store(c,user,'profile_answer',data,id)
def row(c,user,id):return db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='profile_answer'",(id,user)).fetchone())
def owned_experience(c,user,id):
    result=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='experience'",(id,user)).fetchone()) if id else None
    if id and not result:raise HTTPException(404,'Profile experience not found.')
    return result

def experience_ids(value):
    """Explicit arrays, including [], win. Old records remain read-only compatible."""
    return list(dict.fromkeys(value['experience_ids'] if isinstance(value.get('experience_ids'),list) else [value['experience_id']] if value.get('experience_id') else []))

def validate_links(c,user,ids):
    if len(ids)>10 or len(set(ids))!=len(ids):raise HTTPException(400,'Choose up to ten different Profile experiences.')
    for id in ids:
        if not isinstance(id,str) or not id or len(id)>64:raise HTTPException(400,'Choose valid Profile experiences.')
        target=owned_experience(c,user,id)
        if not target['data'].get('confirmed') or target['data'].get('category') not in ('employment','project','education','volunteering','skills','coursework'):raise HTTPException(400,'Choose confirmed roles, projects, education or volunteering records.')
        from . import project_relations
        if project_relations.unresolved(c,user,target['data']):raise HTTPException(422,'Resolve the project’s unavailable related jobs before linking this detail.')
    return ids

def require_links(links):
    if not links:raise HTTPException(422,'Choose at least one related experience before saving this professional Supporting Detail.')

def needs_link(user,data):
    if data.get('answer_kind')!='experience':return False
    links=experience_ids(data)
    if not links:return True
    from . import project_relations
    with db.connect() as c:
        for id in links:
            record=db.decode(c.execute("SELECT * FROM entities WHERE user_id=? AND id=? AND kind='experience'",(user,id)).fetchone())
            if not record or not record['data'].get('confirmed') or project_relations.unresolved(c,user,record['data']):return True
    return False

def stable_questions(data,kind):
    """Assign old questions repeat-safe IDs; edits/status never depend on list position."""
    questions=data.setdefault('questions',[])
    if kind=='resume':
        asked=data.setdefault('asked_questions',copy.deepcopy(questions))
        for q in questions:
            if not any(norm(x['text'])==norm(q['text']) for x in asked):asked.append(copy.deepcopy(q))
        rows=asked
    else:rows=questions
    for q in rows:
        q.setdefault('id',hashlib.sha256((kind+':'+norm(q['text'])).encode()).hexdigest()[:24])
        q.setdefault('status','open');q.setdefault('answer','');q.setdefault('answer_version',0)
    if kind=='resume':
        index={norm(q['text']):q for q in rows}
        data['questions']=[copy.deepcopy(index[norm(q['text'])]) for q in questions]
    return rows

def sync_questions(data,kind):
    rows=stable_questions(data,kind)
    if kind=='resume':
        current={q['id'] for q in data['questions']};data['questions']=[copy.deepcopy(q) for q in rows if q['id'] in current]

def proposal_questions(data,proposal,kind):
    rows=stable_questions(data,kind);ids=proposal.get('question_ids',[])
    return [q for q in rows if q['id'] in ids]

def check_fresh(data,proposal,kind):
    for q in proposal_questions(data,proposal,kind):
        expected=proposal.get('answer_versions',{}).get(q['id'])
        if expected is not None and q['answer_version']!=expected:raise HTTPException(409,'This answer changed after its review proposal. Review the latest answer before approving it.')

def associate_inputs(data,proposal,kind,submitted):
    """Bind only exact submitted answers, independently of model-generated associations."""
    questions={q['id']:q for q in stable_questions(data,kind)}
    quotes=[f['user_quote'] for f in proposal.get('fields',[])] if kind=='resume' else [proposal.get('user_quote','')]
    selected=[questions[a['question_id']] for a in submitted if a.get('question_id') in questions and a.get('answer')==questions[a['question_id']].get('answer')]
    if selected and all(quote.strip() and any(quote in q['answer'] for q in selected) for quote in quotes):
        ids=[q['id'] for q in selected if any(quote in q['answer'] for quote in quotes)]
        proposal.update(question_ids=ids,answer_versions={id:questions[id]['answer_version'] for id in ids})

def reviewed(c,user,conversation_id,data,proposal,kind,mark=True):
    """Called inside the same transaction as approval. Existing source records are not copied."""
    if proposal.get('cleanup_unavailable') and not mark:return None
    if kind=='resume':
        if proposal.get('category')=='authorization':return None
        values=proposal.get('approved_values',{})
        text='\n'.join(v.strip() for v in values.values() if isinstance(v,str) and v.strip())
        answer_kind='experience';experience_id=proposal.get('applied_record_id','');title=proposal.get('approved_title') or proposal.get('title','Experience detail')
        backed={} if proposal.get('evidence_only') else values
    else:
        text=proposal.get('text','');answer_kind=proposal.get('kind','experience');experience_id=proposal.get('applied_record_id') or proposal.get('profile_record_id','');title=proposal.get('title','Letter detail');backed={}
    if not text.strip() or re.search(PRIVATE,text,re.I):return None
    links=experience_ids(proposal) if 'experience_ids' in proposal else [experience_id] if experience_id else []
    links=validate_links(c,user,links)
    if mark and answer_kind=='experience':require_links(links)
    experience_id=links[0] if links else ''
    if proposal.get('profile_answer_id') and row(c,user,proposal['profile_answer_id']):return proposal['profile_answer_id']
    origin=kind+':'+conversation_id+':'+proposal['id'];id=key(user,origin)
    if row(c,user,id):return id
    messages={m['id']:m for m in data.get('messages',[])};message=messages.get(proposal.get('source_message_id'),{})
    questions=proposal_questions(data,proposal,kind)
    source={'builder':kind,'conversation_id':conversation_id,'proposal_id':proposal['id'],'message_id':proposal.get('source_message_id',''),'message':proposal.get('source_message_text') or message.get('text',''),'job_id':data['job_id'],'resume_id':data.get('resume_id',''),'questions':[{'id':q['id'],'text':q['text']} for q in questions],'reviewed_at':proposal.get('reviewed_at') or proposal.get('approved_at') or db.now()}
    from .project_context import provenance
    source.update(provenance(proposal.get('project_refs',[])))
    if kind=='resume':source['proposed_fields']=copy.deepcopy(proposal.get('fields',[]))
    job=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='job'",(data['job_id'],user)).fetchone())
    posting=data.get('posting_snapshot') or (job or {}).get('data',{})
    source.update({k:copy.deepcopy(proposal[k]) for k in ('user_quote','suggested_text','editing_note','improvement_suggestions','career_goal_source') if k in proposal})
    value={'version':1,'status':'confirmed','answer_kind':answer_kind,'title':title,'text':text,'experience_id':experience_id,'experience_ids':links,'category':proposal.get('category') or proposal.get('profile_category','project'),'record_context':{},'backed_fields':backed,'scope':{'job_id':data['job_id'],'company':posting.get('company',''),'role':posting.get('title','')},'sources':[source],'history':[]}
    if kind=='cover':
        sid=proposal.get('related_source_id','');parts=sid.split(':')
        if len(parts)>=3 and parts[0]=='resume' and parts[1].isdigit() and parts[2].isdigit():
            try:value['record_context']=copy.deepcopy(data['resume_snapshot']['sections'][int(parts[1])]['entries'][int(parts[2])])
            except (KeyError,IndexError):pass
        value['record_context']={k:v for k,v in value['record_context'].items() if k in ('title','category','organization','dates','location')}
    # One reviewed fact can be supplied in more than one conversation without duplicating it.
    existing=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)) if (lambda v:v.get('status')=='confirmed' and v.get('answer_kind')==answer_kind and norm(v.get('text'))==norm(text) and experience_ids(v)==links and (answer_kind=='experience' or v.get('scope',{}).get('job_id')==data['job_id']))(json.loads(r['payload']))),None)
    if existing:
        if not any(s.get('conversation_id')==conversation_id and s.get('proposal_id')==proposal['id'] for s in existing['data']['sources']):
            existing['data']['sources'].append(source);write(c,user,existing['data'],existing['id'],allow_unlinked=not mark)
        id=existing['id']
    else:write(c,user,value,id,allow_unlinked=not mark)
    if proposal.get('supersedes_id'):
        old=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)) if any(s.get('proposal_id')==proposal['supersedes_id'] and s.get('conversation_id')==conversation_id for s in json.loads(r['payload']).get('sources',[]))),None)
        if old and old['id']!=id:archive_data=old['data'];archive_data['history'].append({**copy.deepcopy(archive_data),'history':[]});archive_data['status']='archived';archive_data['version']+=1;write(c,user,archive_data,old['id'])
    if mark and answer_kind=='experience':touch_resumes(c,user,conversation_id,experience_id or id)
    proposal['profile_answer_id']=id
    for q in questions:
        q['status']='reviewed';q['reviewed_answer_version']=q['answer_version']
    sync_questions(data,kind)
    return id

def migrate(user):
    """Add references only: no historical PDF, experience, or approved source text is rewritten."""
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        previous={r['id'] for r in c.execute("SELECT id FROM entities WHERE user_id=? AND kind='profile_answer'",(user,))}
        for builder,entity_kind,field in [('resume','resume_conversation','proposals'),('cover','cover_workspace','context_proposals')]:
            for r in c.execute('SELECT * FROM entities WHERE user_id=? AND kind=?',(user,entity_kind)).fetchall():
                record=db.decode(r);data=record['data'];old=json.dumps(data,sort_keys=True);stable_questions(data,builder)
                for p in data.get(field,[]):
                    if p.get('status')=='approved':reviewed(c,user,record['id'],data,p,builder,mark=False)
                if old!=json.dumps(data,sort_keys=True):
                    from .resume_conversation import write as store
                    data['version']+=1;store(c,user,entity_kind,data,record['id'])
        added=[db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)) if r['id'] not in previous and json.loads(r['payload']).get('answer_kind')=='experience']
        if added:touch_resumes(c,user,None,added[0]['data'].get('experience_id') or added[0]['id'])

def confirmed(user):
    rows=[]
    for r in db.list_entities(user,'profile_answer'):
        data=r['data']
        if data.get('status')!='confirmed' or needs_link(user,data):continue
        if data.get('backed_fields'):
            target=db.get(user,data.get('experience_id',''),'experience')
            if not target or not target['data'].get('confirmed') or any(str(value) not in str(target['data'].get(field,'')) for field,value in data['backed_fields'].items()):continue
        rows.append(r)
    return rows

def records(user):
    """Effective confirmed Profile for future requests. No persistent record or historical snapshot changes."""
    from . import project_relations
    records={r['id']:copy.deepcopy(r) for r in db.list_entities(user,'experience') if r['data'].get('confirmed') and project_relations.available(user,r['data'])}
    for answer in confirmed(user):
        a=answer['data']
        if a['answer_kind']!='experience':continue
        links=experience_ids(a);rid=links[0] if links else '';record=records.get(rid)
        if not record:continue
        full='\n'.join(str(v) for v in record['data'].values())
        if norm(a['text']) not in norm(full):record['data']['contribution']='\n'.join(filter(None,[record['data'].get('contribution',''),a['text']]))
        record['data'].setdefault('answer_sources',[]).append({'id':answer['id'],'version':a['version'],'experience_ids':links,'linked_experiences':[{'id':id,'title':records[id]['data']['title']} for id in links if id in records],'association_note':'Use this fact once in its main context. Additional links indicate related work, not separate accomplishments.','text':a['text'],'title':a['title'],'questions':[q['text'] for source in a['sources'] for q in source.get('questions',[])],'provenance':[{k:copy.deepcopy(v) for k,v in source.items() if k in ('builder','draft_id','snapshot_id','analysis_id','commit','excerpts','reviewed_at','proposal_id','conversation_id','job_id','resume_id','project_refs')} for source in a['sources']]})
    for record in records.values():
        if record['data'].get('category')=='project':record['data']['related_jobs']=[{'id':id,'title':records[id]['data']['title'],'organization':records[id]['data'].get('organization','')} for id in record['data'].get('linked_employment_ids',[]) if id in records and records[id]['data'].get('category')=='employment']
    return list(records.values())

def reusable(user,job_id,selected=()):
    """Motivation requires an explicit per-letter selection, even for the same company."""
    allowed=set(selected)
    return [r for r in confirmed(user) if r['data']['answer_kind']=='experience' or r['id'] in allowed]

def drafts(user):
    rows=[]
    for builder,kind in [('resume','resume_conversation'),('cover','cover_workspace')]:
        for record in db.list_entities(user,kind):
            data=record['data']
            for q in stable_questions(data,builder):
                if q.get('cleanup_answer_version')==q.get('answer_version'):continue
                if not q.get('answer') or re.search(PRIVATE,q['answer'],re.I) or (q.get('reviewed_answer_version')==q['answer_version']):continue
                project_ids=list(dict.fromkeys(r['experience_id'] for r in q.get('project_refs',[]) if r.get('experience_id')))
                rows.append({'id':'draft:'+builder+':'+record['id']+':'+q['id'],'kind':'profile_answer','created_at':q.get('answered_at',record['updated_at']),'updated_at':record['updated_at'],'data':{'version':q['answer_version'],'status':'draft','answer_kind':'motivation' if q.get('topic')=='motivation' else 'experience','title':q['text'],'text':q['answer'],'experience_id':project_ids[0] if len(project_ids)==1 else '','sources':[{'builder':builder,'conversation_id':record['id'],'job_id':data['job_id'],'resume_id':data.get('resume_id',''),'questions':[{'id':q['id'],'text':q['text']}],'project_refs':copy.deepcopy(q.get('project_refs',[]))}]}})
    return rows

def listing(user):
    migrate(user)
    return [{**r,'data':{**r['data'],'needs_related_experience':needs_link(user,r['data'])}} for r in db.list_entities(user,'profile_answer')]+drafts(user)+[{'id':r['id'],'kind':'profile_answer','created_at':r['created_at'],'updated_at':r['updated_at'],'data':{**r['data'],'answer_kind':'experience','sources':[{'builder':r['data']['builder'],'draft_id':r['id'],'questions':r['data'].get('questions',[]),'message':r['data'].get('text','')}]}} for r in db.list_entities(user,'answer_draft') if r['data']['status']=='draft']

def edit(user,id,body):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');record=row(c,user,id)
        if not record:raise HTTPException(404,'Reviewed answer not found.')
        data=record['data']
        if data['version']!=body.expected_version:raise HTTPException(409,'This answer changed in another window. Reload before saving.')
        if not body.text.strip() or re.search(PRIVATE,body.text,re.I):raise HTTPException(400,'Keep authorization in private settings. Use a nonempty professional detail or motivation.')
        links=validate_links(c,user,body.experience_ids if body.experience_ids is not None else experience_ids(data) if body.experience_id==data.get('experience_id','') else [body.experience_id] if body.experience_id else [])
        if data['answer_kind']=='experience' and not body.archived:require_links(links)
        if data['answer_kind']=='motivation' and links:raise HTTPException(400,'Personal motivation stays scoped to its opportunity.')
        if data.get('backed_fields') and (links[0] if links else '')!=data.get('experience_id',''):raise HTTPException(400,'Keep the original main experience for Profile-backed facts.')
        old=copy.deepcopy(data);old['history']=[]
        if data.get('backed_fields') and data.get('experience_id'):
            original=owned_experience(c,user,data['experience_id'])
            if body.text!=data['text']:
                if not original or original['updated_at']!=body.experience_updated_at:raise HTTPException(409,'The linked Profile record changed. Reload and review it before correcting these facts.')
                before=data['backed_fields'];values=body.values
                if set(values)!=set(before) or body.text!='\n'.join(v.strip() for v in values.values() if v.strip()):raise HTTPException(400,'Correct each original field so the linked Profile and answer stay consistent.')
                value=copy.deepcopy(original['data'])
                for field,text in values.items():
                    if before[field] not in str(value.get(field,'')):raise HTTPException(409,'The original detail changed in Profile. Edit the current Profile record first.')
                    value[field]=str(value[field]).replace(before[field],text,1)
                value=ExperienceItem.model_validate(value).model_dump()
                from .resume_conversation import write as store
                store(c,user,'experience',value,original['id']);data['backed_fields']=values
        data.setdefault('review_history',[]).append({'reviewed_at':db.now(),'source':'Profile editor','text':body.text.strip(),'values':body.values})
        data['history'].append(old);data.update({'version':data['version']+1,'title':body.title,'text':body.text.strip(),'experience_id':links[0] if links else '','experience_ids':links,'status':'archived' if body.archived else 'confirmed'})
        write(c,user,data,id)
        if data['answer_kind']=='experience' and (data['text']!=old['text'] or data['status']!=old['status'] or experience_ids(data)!=experience_ids(old)):touch_resumes(c,user,None,data.get('experience_id') or id)
    return db.get(user,id,'profile_answer')


def confirm_draft(user,body):
    """Explicit manual review is also available without model access."""
    entity_kind='resume_conversation' if body.builder=='resume' else 'cover_workspace'
    from .resume_conversation import write as store
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');record=db.decode(c.execute('SELECT * FROM entities WHERE id=? AND user_id=? AND kind=?',(body.conversation_id,user,entity_kind)).fetchone())
        if not record:raise HTTPException(404,'Answer conversation not found.')
        data=record['data'];questions=stable_questions(data,body.builder);question=next((q for q in questions if q['id']==body.question_id),None)
        if not question or question['answer_version']!=body.expected_answer_version:raise HTTPException(409,'This answer changed. Reload and review the current text.')
        links=validate_links(c,user,body.experience_ids if body.experience_ids is not None else [body.experience_id] if body.experience_id else [])
        if body.answer_kind=='motivation' and links:raise HTTPException(400,'Personal motivation stays scoped to its opportunity.')
        body=body.model_copy(update={'experience_id':links[0] if links else ''})
        if question.get('project_refs') and body.answer_kind=='experience':
            from .project_context import destination
            ids=list(dict.fromkeys(r['experience_id'] for r in question['project_refs'] if r.get('experience_id')))
            if ids or body.experience_id:
                project_id=next((id for id in links if owned_experience(c,user,id)['data'].get('category')=='project'),'')
                target=destination(c,user,{'evidence_experience_id':ids[0] if len(ids)==1 else ''},project_id or body.experience_id)
                if not links:links=[target['id']]
                body=body.model_copy(update={'experience_id':links[0],'category':'project'})
        if body.answer_kind=='experience':require_links(links)
        if not question['answer'].strip() or not body.text.strip() or re.search(PRIVATE,body.text,re.I):raise HTTPException(400,'Review a nonempty answer; authorization belongs in private settings.')
        if body.experience_id and not owned_experience(c,user,body.experience_id)['data'].get('confirmed'):raise HTTPException(400,'Choose a confirmed experience.')
        origin='manual:'+body.builder+':'+body.conversation_id+':'+body.question_id+':'+str(body.expected_answer_version);id=key(user,origin)
        if not row(c,user,id):
            job=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='job'",(data['job_id'],user)).fetchone())
            posting=(job or {}).get('data',{})
            value={'version':1,'status':'confirmed','answer_kind':body.answer_kind,'title':body.title,'text':body.text.strip(),'experience_id':body.experience_id,'experience_ids':links,'category':body.category,'record_context':{},'backed_fields':{},'scope':{'job_id':data['job_id'],'company':posting.get('company',''),'role':posting.get('title','')},'sources':[{'builder':body.builder,'conversation_id':record['id'],'job_id':data['job_id'],'resume_id':data.get('resume_id',''),'questions':[{'id':question['id'],'text':question['text']}],'message':question['answer'],'project_refs':copy.deepcopy(question.get('project_refs',[])),'reviewed_at':db.now(),'manual_review':True}],'history':[]}
            existing=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)) if (lambda a:a.get('status')=='confirmed' and a.get('answer_kind')==body.answer_kind and norm(a.get('text'))==norm(body.text) and experience_ids(a)==links and (body.answer_kind=='experience' or a.get('scope',{}).get('job_id')==data['job_id']))(json.loads(r['payload']))),None)
            if existing:
                id=existing['id'];sources=existing['data']['sources']
                if not any(s.get('conversation_id')==record['id'] and any(q.get('id')==question['id'] for q in s.get('questions',[])) for s in sources):
                    sources.extend(value['sources']);write(c,user,existing['data'],id)
            else:write(c,user,value,id)
        if body.answer_kind=='experience':
            touch_resumes(c,user,body.conversation_id,body.experience_id or id)
            if body.builder=='resume':data['profile_dirty']=True;data['approved_record_ids']=list(dict.fromkeys(data.get('approved_record_ids',[])+[body.experience_id or id]))
        question['reviewed_answer_version']=question['answer_version'];question['status']='reviewed';question['profile_answer_id']=id;sync_questions(data,body.builder);data['version']+=1;store(c,user,entity_kind,data,record['id'])
    return db.get(user,id,'profile_answer')


def touch_resumes(c,user,exclude=None,record_id=''):
    from .resume_conversation import write as store
    for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='resume_conversation'",(user,)).fetchall():
        if r['id']==exclude:continue
        record=db.decode(r);data=record['data'];data['profile_dirty']=True
        if record_id:data['approved_record_ids']=list(dict.fromkeys(data.get('approved_record_ids',[])+[record_id]))
        data['version']+=1;store(c,user,'resume_conversation',data,record['id'])


def confirm_application_answer(user,application,question,text,description='',context='',experience_ids=None):
    """Explicitly reviewed professional answer enters the existing Supporting Details library."""
    if re.search(PRIVATE,text,re.I) or re.search(PRIVATE,question,re.I):
        raise HTTPException(422,'Private disclosures belong in the encrypted application-answer vault.')
    from .resume_conversation import write as store
    id=key(user,'application:'+application['id']+':'+norm(question)+':'+norm(description)+':'+norm(context)+':'+norm(text))
    with db.connect() as c:
        links=validate_links(c,user,experience_ids or []);require_links(links)
        if not row(c,user,id):
            data=application['data']
            source={'builder':'application_agent','application_id':application['id'],'job_id':data.get('job_id',''),'questions':[{'id':key(user,question),'text':question,'description':description,'context':context}],'reviewed_at':db.now(),'manual_review':True}
            value={'version':1,'status':'confirmed','answer_kind':'experience','title':question[:200],'text':text,'experience_id':links[0],'experience_ids':links,'category':'project','record_context':{},'backed_fields':{},'scope':{'job_id':data.get('job_id',''),'company':data.get('company',''),'role':data.get('title','')},'sources':[source],'history':[]}
            store(c,user,'profile_answer',value,id)
            touch_resumes(c,user,record_id=id)
    return db.get(user,id,'profile_answer')
