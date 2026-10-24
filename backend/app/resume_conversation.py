"""Persistent, account-owned guided builder with immutable rendered revisions."""
from . import project_sources,project_context,task_progress
import asyncio
import base64
import copy
import json
import re
from fastapi import HTTPException
from . import db, ai, ai_settings, optimization, resume_builder, resume_layout, applications, job_parser, resume_data, profile_answers, role_alignment
from .models import ResumeRequest, ExperienceItem, ResumeChatOutput, SettingsUpdate
from .network import ServiceError

def public(value):
    if isinstance(value,dict):return {k:public(v) for k,v in value.items() if k not in ('artifacts','rendered_snapshot','source_snapshot')}
    if isinstance(value,list):return [public(v) for v in value]
    return value

def require(user,id,kind):
    value=db.get(user,id,kind)
    if not value:raise HTTPException(404,'Record not found.')
    return value

def write(c,user,kind,data,id=None):
    id=id or db.uid();stamp=db.now()
    row=c.execute('SELECT user_id,kind FROM entities WHERE id=?',(id,)).fetchone()
    if row and (row['user_id']!=user or row['kind']!=kind):raise HTTPException(404,'Record not found.')
    if row:c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=?',(json.dumps(data),stamp,id))
    else:c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?)',(id,user,kind,json.dumps(data),stamp,stamp))
    from . import onboarding
    onboarding.profile_added(c,user,kind,data)
    c.execute('DELETE FROM evidence_fts WHERE id=? AND user_id=?',(id,user))
    if kind=='experience' and data.get('confirmed'):c.execute('INSERT INTO evidence_fts VALUES(?,?,?,?)',(id,user,kind,json.dumps(data)))
    return id

def mutate(user,id,version,change):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        record=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='resume_conversation'",(id,user)).fetchone())
        if not record:raise HTTPException(404,'Conversation not found.')
        data=record['data']
        if data['version']!=version:raise HTTPException(409,'This conversation changed in another window. Reload it before retrying. Your previous draft remains available.')
        change(data,c);data['version']+=1;write(c,user,'resume_conversation',data,id)
    return require(user,id,'resume_conversation')

def source(user,data,decisions=None,template='education'):
    from .main import build_resume
    ids=[r['id'] for r in profile_answers.records(user)]
    job=require(user,data['job_id'],'job')
    value=build_resume(user,ResumeRequest(job_id=job['id'],analysis_id=data.get('analysis_id'),experience_ids=ids,decisions=decisions or [],template=template))
    value['schema_version']=4
    value['project_snapshot_ids']=list(data.get('project_snapshot_ids',[]))
    return value

def task_running(c,user,id):
    for row in c.execute("SELECT result FROM tasks WHERE user_id=? AND kind='resume_guided' AND status IN ('queued','running')",(user,)):
        inputs=json.loads(row['result'] or '{}').get('inputs',{})
        if inputs.get('conversation_id')==id:return True
    return False

def start(user,body):
    require(user,body.job_id,'job')
    analysis=require(user,body.analysis_id,'analysis') if body.analysis_id else None
    if analysis and analysis['data'].get('job_id')!=body.job_id:raise HTTPException(409,'Choose a comparison for this posting.')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        rows=c.execute("SELECT * FROM entities WHERE user_id=? AND kind='resume_conversation'",(user,)).fetchall()
        existing=next((db.decode(r) for r in rows if json.loads(r['payload'])['job_id']==body.job_id),None)
        if existing:
            id=existing['id']
            if body.analysis_id and existing['data'].get('analysis_id')!=body.analysis_id and not existing['data'].get('profile_dirty') and not task_running(c,user,id):
                existing['data']['analysis_id']=body.analysis_id;existing['data']['version']+=1;write(c,user,'resume_conversation',existing['data'],id)
        else:
            questions=project_context.fresh_questions(user,role_alignment.initial_questions((analysis or {}).get('data'),require(user,body.job_id,'job')['data']))
            data={'job_id':body.job_id,'analysis_id':body.analysis_id,'version':0,'messages':[],'questions':questions[:3],'asked_questions':questions[:3],'proposals':[],'revision_ids':[],'current_revision_id':None,'workspace_token':None,'profile_dirty':False,'approved_record_ids':[]}
            id=write(c,user,'resume_conversation',data)
    if analysis:
        seed_questions(user,id,analysis)
    return state(user,id)

def seed_questions(user,id,analysis):
    posting=require(user,analysis['data']['job_id'],'job')['data']
    candidates=project_context.fresh_questions(user,role_alignment.initial_questions(analysis['data'],posting))
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        record=db.decode(c.execute("SELECT * FROM entities WHERE user_id=? AND id=? AND kind='resume_conversation'",(user,id)).fetchone());data=record['data']
        if task_running(c,user,id):return
        marker=analysis['id']+':duties:'+str(role_alignment.VERSION)+':questions:2'
        if data.get('question_context')==marker:return
        asked=profile_answers.stable_questions(data,'resume')
        # Retain every old answer and editable local buffer in question history.
        # Unanswered posting-only prompts must not outrank the assessed questions.
        for q in asked:
            seeded=q.get('topic')=='job_duty' or q.get('reason','').startswith('Clarify this explicit qualification:') or q['text'].startswith('Is there a relevant project or accomplishment')
            if seeded and not q.get('answer') and q.get('status') not in ('reviewed','answered','skipped'):
                matching=any(v.get('criterion_id')==q.get('criterion_id') and v['text']==q['text'] for v in candidates)
                if not matching:q['status']='superseded'
                elif q.get('status')=='superseded':q['status']='open'
        active=[q for q in asked if q.get('status')!='superseded']
        seen={q.get('criterion_id') for q in active if q.get('criterion_id')}
        seen_text={q['text'].strip().casefold() for q in active}
        new=[q for q in candidates if q.get('criterion_id') not in seen and q['text'].strip().casefold() not in seen_text]
        # Current questions receive the comparison's supporting excerpts as context.
        by_criterion={q.get('criterion_id'):q for q in candidates}
        for q in active:
            if q.get('criterion_id') in by_criterion:
                q.update({k:v for k,v in by_criterion[q['criterion_id']].items() if k in ('profile_evidence','assessment_explanation')})
                if not q.get('answer') and q.get('status') not in ('reviewed','answered','skipped'):
                    q['project_refs']=copy.deepcopy(by_criterion[q['criterion_id']].get('project_refs',[]))
        data['asked_questions']=asked+new[:3]
        data['questions']=active+new[:3]
        data['question_context']=marker;profile_answers.stable_questions(data,'resume')
        data['version']+=1;write(c,user,'resume_conversation',data,id)

def state(user,id):
    record=require(user,id,'resume_conversation');data=record['data'];profile_answers.stable_questions(data,'resume')
    current=require(user,data['current_revision_id'],'resume_revision') if data.get('current_revision_id') else None
    result=public(record);result['current']=public(current)
    result['revisions']=[{'id':r['id'],'created_at':r['created_at'],'summary':r['data']['summary']} for rid in data['revision_ids'] if (r:=db.get(user,rid,'resume_revision'))]
    if not current:
        try:result['catalog']=resume_builder.catalog(source(user,data))
        except (ServiceError,HTTPException):result['catalog']=[]
    result['saved_versions']=[public(applications.public(r)) for r in db.list_entities(user,'resume') if r['data'].get('job_id')==data['job_id']]
    with db.connect() as c:
        tasks=c.execute("SELECT id,status,error,result,updated_at FROM tasks WHERE user_id=? AND kind='resume_guided' ORDER BY created_at DESC LIMIT 20",(user,)).fetchall()
    own_tasks=[r for r in tasks if id in (r['result'] or '')]
    result['pending_task']=next((r['id'] for r in own_tasks if r['status'] in ('queued','running')),None)
    result['last_failure']=own_tasks[0]['error'] if own_tasks and own_tasks[0]['status'] in ('failed','interrupted') and own_tasks[0]['updated_at']>record['updated_at'] else None
    result['preview_stale']=bool(current and current['data']['request_token']!=data.get('workspace_token'))
    if result['last_failure'] and result['preview_stale']:
        inputs=json.loads(own_tasks[0]['result'] or '{}').get('inputs') or {}
        messages=result['data']['messages']
        # Older saved conversations predate revision outcome markers. Describe the
        # failed response truthfully without rewriting their stored history.
        if inputs.get('text') and len(messages)>=2 and messages[-1]['role']=='assistant' and messages[-2]['role']=='user' and messages[-2]['text']==inputs['text']:
            if 'revision_status' not in messages[-1]:messages[-1]['revision_status']='failed'
            result['data'].setdefault('last_message_input',inputs['text'])
    return result

def require_initial_comparison(user,id):
    data=require(user,id,'resume_conversation')['data']
    if data.get('current_revision_id'):return  # Preserve recovery/refinement of established drafts.
    analysis=db.get(user,data.get('analysis_id'),'analysis') if data.get('analysis_id') else None
    posting=require(user,data['job_id'],'job')['data']
    checked=(analysis or {}).get('data',{})
    if not analysis or checked.get('schema_version')!=3 or checked.get('posting_hash')!=job_parser.organize(posting)['text_hash']:
        raise HTTPException(409,'Compare your Profile to this posting first. The comparison reviews saved experience before asking for missing details.')

def empty_preparation(data):
    request=data.get('workspace_request')
    return bool(not data.get('current_revision_id') and request is not None and not request.get('experience_ids') and not any((request.get('content') or {}).values()))

def begin(user,id,version,token=None,message=None,preparation=None):
    def change(data,c):
        if token:data['workspace_token']=token
        if preparation is not None:data['workspace_request']=preparation
        if message:data['last_message_input']=message;data['messages'].append({'id':db.uid(),'role':'user','text':message,'created_at':db.now()})
    return mutate(user,id,version,change)

def save_revision(user,id,version,snapshot,catalog,summary,token,usage=None,source_snapshot=None,draft_id=None):
    revision_id=db.uid()
    def change(data,c):
        # Both revision and head update commit together. Late results cannot replace a newer head.
        if token!=data['workspace_token']:raise HTTPException(409,'A newer preview request superseded this result.')
        value={'conversation_id':id,'job_id':data['job_id'],'parent_id':data['current_revision_id'],'snapshot':snapshot,'catalog':catalog,'summary':summary,'request_token':token,'usage':usage,'draft_id':draft_id,'source_snapshot':source_snapshot,'project_snapshot_ids':list(data.get('project_snapshot_ids',[]))}
        write(c,user,'resume_revision',value,revision_id)
        data['revision_ids'].append(revision_id);data['current_revision_id']=revision_id;data.pop('workspace_request',None)
        if usage:
            data['approved_record_ids']=[];data.pop('pending_feedback',None)
            pending=data.pop('pending_revision_message_id',None)
            for message in data['messages']:
                if message['id']==pending:message['revision_status']='applied'
            data.pop('last_message_input',None)
        if usage:data['messages'].append({'id':db.uid(),'role':'assistant','text':summary,'usage':usage,'created_at':db.now()})
    mutate(user,id,version,change)
    return state(user,id)

async def build(user,id,version,mode,decisions=None,template='education',feedback=None,manual=False,preparation=None):
    task_progress.stage('preparing')
    data=require(user,id,'resume_conversation')['data']
    if data['version']!=version:raise HTTPException(409,'Reload the conversation before building.')
    if data.get('workspace_request') and not empty_preparation(data):raise HTTPException(409,'Render or restore your retained local edits before requesting an AI revision.')
    prepared=preparation or (ResumeRequest.model_validate(data['workspace_request']) if empty_preparation(data) else None)
    if prepared:
        if data.get('current_revision_id') or prepared.experience_ids or any((prepared.content or {}).values()):raise HTTPException(409,'Render your selected content before requesting an AI revision.')
        if prepared.job_id!=data['job_id'] or prepared.analysis_id!=data.get('analysis_id'):raise HTTPException(409,'First-draft inputs belong to another posting or comparison. Reload before building.')
        if preparation is not None:decisions=prepared.decisions
        elif not decisions:decisions=prepared.decisions
        template=prepared.template
        # Validate source ownership, stable item IDs and edit limits before any provider dispatch.
        prepared_snapshot=source(user,data,decisions,template)
        optimization.apply(prepared_snapshot,{'entries':[],'headline':prepared.headline if prepared.headline is not None else prepared_snapshot['headline']},prepared.overrides)

    if not manual and data.get('analysis_id') and not data['profile_dirty']:
        checked=require(user,data['analysis_id'],'analysis')['data'];posting=require(user,data['job_id'],'job')['data']
        if checked.get('schema_version')!=3 or checked.get('posting_hash')!=job_parser.organize(posting)['text_hash']:raise HTTPException(409,'Rerun the comparison for this posting before building an AI revision. The previous draft remains available.')
    if feedback is None and data.get('pending_feedback'):feedback=data['pending_feedback']
    token=db.uid();record=begin(user,id,version,token,preparation=prepared.model_dump() if prepared else None);version=record['data']['version'];data=record['data']
    current=require(user,data['current_revision_id'],'resume_revision')['data'] if data.get('current_revision_id') else None
    comparison_usage=None
    if data['profile_dirty'] and not manual:
        task_progress.stage('comparison')
        job=require(user,data['job_id'],'job');result=await ai.analyze(user,job['data'],mode)
        analysis=db.save(user,'analysis',{**result,'job_id':job['id']});comparison_usage=result['ai']
        def refresh(d,c):d.update({'analysis_id':analysis['id'],'profile_dirty':False})
        record=mutate(user,id,version,refresh);version=record['data']['version'];data=record['data']
    # Suggested edits refer to their original analysis. Approved facts append rather than replace source text.
    snapshot=source(user,data,decisions if not data['profile_dirty'] and not comparison_usage else [],(feedback or {}).get('template') if (feedback or {}).get('template') in ('education','experience') else current['snapshot']['template'] if current else template)
    if prepared:
        snapshot=optimization.apply(snapshot,{'entries':[],'headline':prepared.headline if prepared.headline is not None else snapshot['headline']},prepared.overrides)
        snapshot['profile']['headline']=snapshot['headline']
        if prepared.title!='Tailored resume':snapshot['title']=prepared.title
    if current:
        # Preserve reviewed text without turning chat messages into evidence.
        old={i['item_id']:i for s in current['snapshot']['sections'] for e in s['entries'] for i in e['content_items']}
        for s in snapshot['sections']:
            for e in s['entries']:
                for n,item in enumerate(e['content_items']):
                    if item['item_id'] in old:item['text']=old[item['item_id']]['text'];e['bullets'][n]=item['text']
    if manual:
        task_progress.stage('fitting')
        fitted=await asyncio.to_thread(resume_builder.fit,snapshot,resume_builder.catalog(snapshot))
        task_progress.stage('rendering')
        rendered=await asyncio.to_thread(resume_layout.render,resume_builder.select(snapshot,fitted['content'],fitted['experience_ids']))
        task_progress.stage('saving')
        return save_revision(user,id,version,rendered,resume_builder.catalog(snapshot),'Built a locally fitted draft. Review the content before saving.',token,source_snapshot=snapshot)
    analysis=require(user,data['analysis_id'],'analysis')['data'] if data.get('analysis_id') else None
    feedback={**(feedback or {}),'approved_record_ids':data['approved_record_ids']}
    if prepared and prepared.headline is not None and prepared.headline!=db.settings(user).get('headline',''):feedback['prepared_headline']=prepared.headline
    draft=await optimization.create(user,snapshot,analysis,mode,feedback,guided=True,current=current['snapshot'] if current else None)
    result=draft['data'];rendered=result['rendered_snapshot'];rendered['draft_id']=draft['id']
    rendered['optimization']={k:result[k] for k in ('ai','audit_ai','actual_cost_usd','headline_evidence','keywords','source_checked')}
    usage={k:result.get(k) for k in ('ai','audit_ai','layout_ai','actual_cost_usd')};usage['comparison_ai']=comparison_usage
    if comparison_usage and usage['actual_cost_usd'] is not None:usage['actual_cost_usd']+=comparison_usage.get('estimated_token_cost_usd') or 0
    summary='Built your first tailored draft and updated its actual PDF. Review the headline, wording, and included content.'
    if current:
        before={i['item_id']:i['text'] for s in current['snapshot']['sections'] for e in s['entries'] for i in e['content_items']}
        after={i['item_id']:i['text'] for s in rendered['sections'] for e in s['entries'] for i in e['content_items']}
        changes=[]
        if current['snapshot']['headline']!=rendered['headline']:changes.append('Updated the headline.')
        count=sum(before[k]!=after[k] for k in before.keys()&after.keys())
        if count:changes.append(f'Revised {count} wording items.')
        if after.keys()-before.keys():changes.append(f'Added {len(after.keys()-before.keys())} content items.')
        if before.keys()-after.keys():changes.append(f'Omitted {len(before.keys()-after.keys())} content items.')
        if current['snapshot']['template']!=rendered['template']:changes.append('Updated the section order.')
        if comparison_usage:changes.append('Refreshed qualifications using approved Profile details.')
        summary=' '.join(changes) or 'Rechecked the draft; your reviewed content was preserved.'
    updated=save_revision(user,id,version,rendered,result['catalog'],summary,token,usage,snapshot,draft['id'])
    return updated

async def send(user,id,body):
    record=begin(user,id,body.expected_version,message=body.text);data=record['data'];version=data['version']
    records=profile_answers.records(user);current=require(user,data['current_revision_id'],'resume_revision')['data'] if data.get('current_revision_id') else None
    job=require(user,data['job_id'],'job');criteria=job_parser.criteria(job['data'])+role_alignment.catalog(job['data'])
    analysis=(db.get(user,data.get('analysis_id'),'analysis') or {}).get('data',{})
    materials=project_sources.context(user,data)
    task_progress.stage('reviewing')
    output,meta=await ai.structured(ResumeChatOutput,{'task':'''Continue a focused resume conversation. Consider saved project analyses automatically, but only as context for posting-specific questions, never confirmed applicant facts. Put project-specific follow-ups in project_questions with exact project_context_ids from that context; put only other questions in questions. Reuse already confirmed answers and ask at most three questions total. Ask concrete, nonrepeated questions about actual contributions, audience, methods or outcomes; explain relevance. Never ask for invented metrics. Distinguish facts from wording/layout instructions. New factual details must be proposals, NEVER used in a revision before explicit human approval. Each field value must be an EXACT contiguous excerpt of the latest user message, with user_quote containing it. For narrative fields only (description, contribution, accomplishments), also provide suggested_value as polished professional wording: fix grammar, remove repetition, organize actions, methods and supported outcomes. Expand only explanations already supported by that exact quote. Never invent tools, numbers, outcomes, validation success or personal ownership. Preserve uncertainty, incomplete work, team boundaries and intent versus measured results. Keep raw value and user_quote unchanged. Provide an editing_note explaining changes and up to three optional improvement_suggestions asking for useful missing details; never insert those missing details as facts. Do not polish structured or private authorization fields. Use an existing record_id only for the same role/project; empty record_id creates a separate record. Allowed narrative fields: description, contribution, accomplishments, tools, relevant_courses, honors; structured fields use the supplied Profile schema. Authorization is category authorization, fields us_citizen/authorized_us/sponsorship_now/sponsorship_future with yes/no/unsure values. Citizenship is distinct from work authorization. Direct eligibility questions to private Profile settings; do not ask them in the professional-experience question group. No proposals for ordinary shortening/emphasis/layout requests. For actionable wording feedback action=revise, identify exact target item and record IDs; preserve unrelated text/selection. Set change_selection only when requested; change_headline only when requested. Set template=education or experience only if the user requests that section ordering; otherwise unchanged. A question-only response action=question leaves draft unchanged. Do not repeat questions already asked. revision_instruction contains only wording/layout instructions, never unapproved factual assertions.''','unreviewed_project_material_for_questions_only':materials,'submitted_question_answers':body.question_answers,'latest_user_message':body.text,'messages':data['messages'][-30:],'previous_questions':data.get('asked_questions',data['questions']),'proposals':data['proposals'],'criterion_catalog':criteria,'duty_alignment':role_alignment.rows(analysis,job['data']),'question_rules':'Use unresolved duty and qualification evidence to ask specific nonrepeated questions. Ask what the user personally did, how, for whom, and what outcome is supported. Already reviewed stories are in confirmed_profile. Reuse facts already present there; do not propose duplicate copies as new facts. Never infer a lack of experience; never ask for invented metrics or external research.','confirmed_profile':[{'id':r['id'],'data':r['data']} for r in records if r['data'].get('confirmed')],'current_draft':public(current),'profile_fields':list(ExperienceItem.model_fields)},body.mode)
    allowed_records={r['id']:r for r in records};criterion_ids={r['id'] for r in criteria}
    known_items={i['item_id'] for r in (current or {}).get('catalog',[]) for i in r['items']}
    if set(output['target_item_ids'])-known_items or set(output['target_record_ids'])-set(allowed_records):raise ServiceError('The feedback referred to unavailable content. Your message is saved; retry with the item name.')
    proposals=[]
    for proposal in output['proposals']:
        rid=proposal['record_id'];old=allowed_records.get(rid)
        if rid and not old:raise ServiceError('A proposed Profile update referred to an unavailable record.')
        if old and old['data']['category']!=proposal['category']:raise ServiceError('A proposed update used the wrong Profile section.')
        if set(proposal['criterion_ids'])-criterion_ids:raise ServiceError('A proposal referred to an unknown qualification.')
        private=proposal['category']=='authorization';allowed={'us_citizen','authorized_us','sponsorship_now','sponsorship_future'} if private else set(ExperienceItem.model_fields)-{'confirmed','source_document_id','source_entry_id','skill_items','category','title'}
        if not proposal['fields'] or len({f['field'] for f in proposal['fields']})!=len(proposal['fields']):raise ServiceError('The Profile proposal has missing or repeated fields.')
        if not private and re.search(r'\b(citizenship|citizen|sponsorship|work authorization|authori[sz]ed to work|visa status)\b',' '.join(f['value'] for f in proposal['fields']),re.I):raise ServiceError('Work authorization belongs in private Profile settings. Ask for a private authorization proposal; it cannot be added as employer-facing experience.')
        for f in proposal['fields']:
            if f['field'] not in allowed or f['user_quote'] not in body.text or (not private and f['value'] not in f['user_quote']) or (private and f['value'] not in ('yes','no','unsure')):raise ServiceError('The proposed facts could not be traced to your message. Your message is saved; retry with the exact details.')
            if f.get('suggested_value'):
                if private or f['field'] not in ('description','contribution','accomplishments'):raise ServiceError('Only professional narrative wording can be polished.')
                from .cover_context import checked_suggestion
                checked_suggestion({'suggested_text':f['suggested_value']},f['user_quote'])
        if old and not db.get(user,rid,'experience'):
            proposal={**proposal,'record_id':'','library_parent_id':rid};rid=''
        item={**proposal,'id':db.uid(),'status':'pending','source_message_id':data['messages'][-1]['id'],'expected_updated_at':old['updated_at'] if old else None,'original':old['data'] if old else {k:v for k,v in db.settings(user).items() if k in ('us_citizen','authorized_us','sponsorship_now','sponsorship_future')} if private else None}
        profile_answers.associate_inputs(data,item,'resume',body.question_answers)
        project_context.bind_proposal(user,data,item,'resume')
        proposals.append(item)
    project_questions=[{'text':q['text'],'reason':'Clarify this project for the posting','criterion_id':None,'project_refs':project_context.references(q['project_context_ids'],materials)} for q in output.get('project_questions',[])]
    revising=bool(current and output['action']=='revise' and not proposals)
    assistant_id=db.uid()
    def append(d,c):
        d['messages'].append({'id':assistant_id,'role':'assistant','text':output['message'],'created_at':db.now(),'usage':{'ai':meta,'actual_cost_usd':meta.get('estimated_token_cost_usd')},**({'revision_status':'pending'} if revising else {})})
        if revising:d['pending_revision_message_id']=assistant_id
        seen={q['text'].strip().casefold() for q in d.get('asked_questions',d['questions'])}
        new=[{'text':q,'reason':'Improve the resume evidence','criterion_id':None} for q in output['questions'] if q.strip().casefold() not in seen]
        new.extend(q for q in project_questions if q['text'].strip().casefold() not in seen)
        new=project_context.fresh_questions(user,new)[:3]
        d['questions']=new;d.setdefault('asked_questions',[]).extend(new)
        d['proposals']+=proposals;d.pop('last_message_input',None)
        if proposals or revising:d['pending_feedback']={k:output.get(k) for k in ('revision_instruction','target_item_ids','target_record_ids','change_headline','change_selection','template')}
    updated=mutate(user,id,version,append)
    if revising:
        try:return await build(user,id,updated['data']['version'],body.mode,feedback=output)
        except (Exception,asyncio.CancelledError):
            # Retain the interpreted request and mark its response as unapplied, without
            # changing the current revision or overwriting a concurrent successful head.
            with db.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='resume_conversation'",(id,user)).fetchone()
                if row:
                    saved=db.decode(row)['data']
                    if saved.get('pending_revision_message_id')==assistant_id:
                        for message in saved['messages']:
                            if message['id']==assistant_id:message['revision_status']='failed'
                        saved['last_message_input']=body.text;saved['version']+=1
                        write(c,user,'resume_conversation',saved,id)
            raise
    return state(user,id)

def approve(user,id,body):
    def change(data,c):
        proposal=next((p for p in data['proposals'] if p['id']==body.proposal_id),None)
        if not proposal:raise HTTPException(404,'Proposal not found.')
        if proposal['status']!='pending':raise HTTPException(409,'This proposal has already been reviewed.')
        profile_answers.check_fresh(data,proposal,'resume')
        if body.action=='reject':proposal['status']='rejected';return
        allowed={f['field'] for f in proposal['fields']}
        if set(body.values)-allowed:raise HTTPException(400,'Only the proposed fields can be approved.')
        values={f['field']:body.values.get(f['field'],f['value']).strip() for f in proposal['fields']}
        if any(not v for v in values.values()):raise HTTPException(400,'A proposed addition is empty. Correct it or reject the proposal.')
        rid=proposal['record_id'];private=proposal['category']=='authorization'
        if private:
            row=c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone();settings=json.loads(row['settings'])
            if any(settings.get(k)!=proposal['original'].get(k) for k in values):raise HTTPException(409,'Work authorization changed since this proposal. Ask again using the current Profile.')
            validated=SettingsUpdate.model_validate(values).model_dump(exclude_none=True)
            c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps({**settings,**validated}),user))
        elif proposal.get('evidence_only'):
            target=project_context.destination(c,user,proposal,body.evidence_experience_id,body.evidence_expected_updated_at,body.keep_standalone)
            rid=target['id'] if target else '';proposal['applied_record_id']=rid;proposal['category']='project'
            data['approved_record_ids']=list(dict.fromkeys(data['approved_record_ids']+([rid] if rid else [])))
        else:
            existing=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='experience'",(rid,user)).fetchone()) if rid else None
            if rid and (not existing or existing['updated_at']!=proposal['expected_updated_at']):raise HTTPException(409,'This Profile record changed since the proposal. Reload and ask for a new proposal; newer details were preserved.')
            parent=next((r for r in profile_answers.records(user) if r['id']==proposal.get('library_parent_id')),None) if proposal.get('library_parent_id') else None
            original=existing['data'] if existing else {k:v for k,v in parent['data'].items() if k in ExperienceItem.model_fields} if parent else ExperienceItem(title=body.title or proposal['title'],category=proposal['category']).model_dump()
            value=copy.deepcopy(original)
            for key,text in values.items():
                if key in ('description','contribution','accomplishments','tools','relevant_courses','honors') and value.get(key):value[key]=value[key] if text in value[key] else value[key]+'\n'+text
                else:value[key]=text
            if body.title:value['title']=body.title
            value['confirmed']=True;value=ExperienceItem.model_validate(value).model_dump()
            rid=write(c,user,'experience',value,rid or None)
            if proposal.get('library_parent_id'):
                parent_answer=profile_answers.row(c,user,proposal['library_parent_id'])
                if parent_answer:
                    parent_answer['data']['experience_id']=rid;parent_answer['data']['experience_ids']=[rid]+[id for id in profile_answers.experience_ids(parent_answer['data']) if id!=rid];parent_answer['data']['version']+=1;profile_answers.write(c,user,parent_answer['data'],parent_answer['id'])
            proposal['applied_record_id']=rid;data['approved_record_ids']=list(dict.fromkeys(data['approved_record_ids']+[rid]))
        proposal.update({'status':'approved','approved_values':values,'approved_at':db.now(),'approved_title':body.title or proposal['title']})
        aid=profile_answers.reviewed(c,user,id,data,proposal,'resume')
        if proposal.get('evidence_only') and not rid and aid:data['approved_record_ids']=list(dict.fromkeys(data['approved_record_ids']+[aid]))
        data['profile_dirty']=True
    mutate(user,id,body.expected_version,change)
    return state(user,id)

def render(user,id,body):
    task_progress.stage('rendering')
    token=body.request_token
    def retain(d,c):d.update({'workspace_token':token,'workspace_request':body.resume.model_dump()})
    record=mutate(user,id,body.expected_version,retain);data=record['data'];version=data['version']
    current=require(user,data['current_revision_id'],'resume_revision')['data'] if data.get('current_revision_id') else None
    if body.resume.job_id!=data['job_id']:raise HTTPException(409,'Preview content belongs to another posting.')
    full=copy.deepcopy(current['source_snapshot']) if current else source(user,data,body.resume.decisions,body.resume.template)
    if current:
        # Use revision catalog text, including previously reviewed rewrites and manual overrides.
        rows={r['id']:r for r in current['catalog']}
        for s in full['sections']:
            for e in s['entries']:
                row=rows.get(e['source_id'])
                if row:e['content_items']=copy.deepcopy(row['items']);e['bullets']=[i['text'] for i in row['items']]
    rows=resume_builder.catalog(full);available={r['id'] for r in rows}
    if set(body.resume.experience_ids)-available:raise HTTPException(400,'Select only content from this revision.')
    full=optimization.apply(full,{'entries':[],'headline':body.resume.headline if body.resume.headline is not None else (current['snapshot']['headline'] if current else full['headline'])},body.resume.overrides)
    full['decisions']=[d.model_dump() for d in body.resume.decisions]
    full['template']=body.resume.template
    full['compact_skills']=body.resume.compact_skills
    if current and current['snapshot'].get('optimization'):full['optimization']=copy.deepcopy(current['snapshot']['optimization'])
    order=['education','employment','project','volunteering','coursework','skills'] if body.resume.template=='education' else ['employment','project','volunteering','education','coursework','skills']
    full['sections'].sort(key=lambda s:next((order.index(e['category']) for e in s['entries']),99))
    parts=body.resume.content if body.resume.content is not None else {r['id']:list(range(len(r['items']))) for r in rows}
    for rid,indices in parts.items():
        row=next((r for r in rows if r['id']==rid),None)
        if not row or len(set(indices))!=len(indices) or any(i<0 or i>=len(row['items']) for i in indices):raise HTTPException(400,'Invalid content selection.')
    selected=resume_builder.select(full,parts,body.resume.experience_ids)
    if not selected['experience_ids']:raise ServiceError('Select at least one meaningful record to render.'+(' Your previous preview remains available.' if current else ' Choose Build first draft to select and fit your Profile content.'))
    for s in selected['sections']:
        for e in s['entries']:
            if e['category']=='project' and not any(i['field'] in ('description','contribution','accomplishment') for i in e['content_items']):raise ServiceError('Include a descriptive bullet for '+e['title']+' or omit that project.')
    rendered=resume_layout.render(selected)
    task_progress.stage('saving')
    return save_revision(user,id,version,rendered,resume_builder.catalog(full),'Updated the preview from your local edits. No AI request.',token,source_snapshot=full,draft_id=(current or {}).get('draft_id'))

def restore(user,id,body):
    revision=require(user,body.revision_id,'resume_revision')
    if revision['data']['conversation_id']!=id:raise HTTPException(409,'That revision belongs to another conversation.')
    def change(data,c):data.update({'current_revision_id':revision['id'],'workspace_token':revision['data']['request_token']})
    mutate(user,id,body.expected_version,change)
    return state(user,id)

def finalize(user,id,body):
    revision=require(user,body.revision_id,'resume_revision');value=revision['data'];snapshot=copy.deepcopy(value['snapshot'])
    if value['conversation_id']!=id:raise HTTPException(409,'That revision belongs to another posting.')
    def change(data,c):
        if data['current_revision_id']!=revision['id'] or data['workspace_token']!=value['request_token']:raise HTTPException(409,'The preview is no longer current. Render and review the latest revision before saving.')
        if snapshot['layout']['pages']!=1 or not snapshot['layout']['validated']:raise HTTPException(409,'Shorten this draft to one page before saving employer downloads.')
        saved=value.get('finalized_resume_id')
        if not saved:
            snapshot.update({'conversation_id':id,'revision_id':revision['id'],'title':resume_data.resume_title(snapshot.get('posting_snapshot'),snapshot.get('title') or 'Resume',snapshot.get('name') or '')})
            saved=write(c,user,'resume',snapshot);value['finalized_resume_id']=saved;write(c,user,'resume_revision',value,revision['id'])
        data['last_saved_resume_id']=saved
    record=mutate(user,id,body.expected_version,change)
    saved=require(user,record['data']['last_saved_resume_id'],'resume');applications.attach_resume(user,saved)
    return state(user,id)

def estimate(user,id,mode):
    data=require(user,id,'resume_conversation')['data'];snapshot=source(user,data)
    base=optimization.estimate(snapshot,mode,db.settings(user));option=ai_settings.resolve(db.settings(user),mode)
    current=db.get(user,data.get('current_revision_id',''),'resume_revision') if data.get('current_revision_id') else None
    context_size=len(json.dumps(snapshot))+len(json.dumps(data['messages'][-30:]))+len(json.dumps(data['proposals']))+len(json.dumps(public(current)))
    extra=ai_settings.estimate(option['model'],option['reasoning_effort'],max(3000,context_size//4)+7000,4500,service_tier=option['service_tier'])
    # Reserve one layout pass plus chat; approved new facts also require reassessment.
    multiplier=2 if data['profile_dirty'] else 1
    base['usd']=round(base['usd']+extra['usd']*multiplier,6) if base['usd'] is not None and extra['usd'] is not None else None
    base['note']='Planning estimate for chat, drafting, final source check, and at most one measured layout wording pass. Approved facts may add a comparison refresh. A question-only reply costs less; actual usage is shown afterward. Local previews, saving and downloads make no provider requests.'
    return base


def adopt(user,id,body):
    data=require(user,id,'resume_conversation')['data'];draft=require(user,body.draft_id,'resume_draft')['data']
    if draft['job_id']!=data['job_id']:raise HTTPException(409,'That draft belongs to another posting.')
    snapshot=source(user,data)
    if draft.get('source_fingerprint')!=optimization.fingerprint(snapshot):raise HTTPException(409,'The Profile changed since this historical draft. Its wording remains available, but build a fresh draft to use current sources.')
    if draft.get('posting_hash')!=job_parser.organize(snapshot['posting_snapshot'])['text_hash']:raise HTTPException(409,'The posting changed since this historical draft. Build a fresh draft for the current posting.')
    for section in snapshot['sections']:
        for entry in section['entries']:
            for n,item in enumerate(entry['content_items']):
                item['text']=draft.get('baseline',{}).get(item['item_id'],item['text']);entry['bullets'][n]=item['text']
    token=db.uid();record=begin(user,id,body.expected_version,token)
    proposal=optimization.apply(snapshot,draft)
    rendered=resume_layout.render(resume_builder.select(proposal,draft['content'],draft['experience_ids']))
    rendered['optimization']={k:draft.get(k) for k in ('ai','audit_ai','actual_cost_usd','headline_evidence','keywords','source_checked')}
    return save_revision(user,id,record['data']['version'],rendered,resume_builder.catalog(proposal),'Opened a historical AI draft as a new working revision. Review its current PDF before saving.',token,source_snapshot=snapshot,draft_id=body.draft_id)
