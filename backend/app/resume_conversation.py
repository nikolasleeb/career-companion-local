"""Persistent, account-owned guided builder with immutable rendered revisions."""
from . import project_sources,project_context,task_progress,linked_project_evidence,resume_quality
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
    if kind=='job' and value['data'].get('description_incomplete'):raise ServiceError('Review the full posting text before using this provider description snippet for tailoring.')
    return value

def write(c,user,kind,data,id=None):
    id=id or db.uid();stamp=db.now()
    row=c.execute('SELECT user_id,kind,payload FROM entities WHERE id=?',(id,)).fetchone()
    if row and (row['user_id']!=user or row['kind']!=kind):raise HTTPException(404,'Record not found.')
    from . import skill_details
    if kind=='experience':
        from . import course_evidence
        previous=json.loads(row['payload']) if row else {}
        data=course_evidence.prepare(data,previous)
        data=skill_details.prepare(c,user,id,data,previous)
    if kind=='profile_answer' and data.get('status')!='archived':skill_details.validate_ref(c,user,data)
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
    if data.get("linked_project_placements"):
        value=linked_project_evidence.apply(value,linked_project_evidence.checked(user,data["linked_project_placements"]))
    else:value=linked_project_evidence.automatic(value)
    value['schema_version']=4
    value['document_format_version']=5
    value['separate_certifications']=True
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
            from . import job_cache
            if not job_cache.is_active(user,body.job_id):raise HTTPException(409,'This posting is expired or closed. Existing application history remains available.')
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
    if result['last_failure']:
        saved=json.loads(own_tasks[0]['result'] or '{}');inputs=saved.get('_task_inputs',saved.get('inputs',{})) or {}
        operation=inputs.get('operation')
        # Recover action intent only; current form values stay client-reviewed.
        # Do not send saved prompts, arbitrary task inputs or account settings.
        if (operation in ('build','build?manual=true') or (operation is None and 'template' in inputs and 'decisions' in inputs)) and not inputs.get('text'):
            result['failed_build_action']={'operation':operation or 'build','asTask':True,'body':{'refresh_linked_evidence':bool(inputs.get('refresh_linked_evidence'))}}
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
    if not analysis or checked.get('schema_version')!=3 or checked.get('posting_hash')!=job_parser.posting_hash(posting):
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

def save_revision(user,id,version,snapshot,catalog,summary,token,usage=None,source_snapshot=None,draft_id=None,quality_only=False):
    snapshot=copy.deepcopy(snapshot)
    revision_id=db.uid()
    def change(data,c):
        # Both revision and head update commit together. Late results cannot replace a newer head.
        if token!=data['workspace_token']:raise HTTPException(409,'A newer preview request superseded this result.')
        resume_quality.invalidate(snapshot)
        value={'conversation_id':id,'job_id':data['job_id'],'parent_id':data['current_revision_id'],'snapshot':snapshot,'catalog':catalog,'summary':summary,'request_token':token,'usage':usage,'draft_id':draft_id,'source_snapshot':source_snapshot,'project_snapshot_ids':list(data.get('project_snapshot_ids',[]))}
        write(c,user,'resume_revision',value,revision_id)
        data.pop('optimization_waiting',None)
        data['revision_ids'].append(revision_id);data['current_revision_id']=revision_id;data.pop('workspace_request',None)
        if snapshot.get('optimization',{}).get('user_constraints') is not None:
            data['user_constraints']=copy.deepcopy(snapshot['optimization']['user_constraints'])
        if usage and not quality_only:
            data['approved_record_ids']=[];data.pop('pending_feedback',None)
            pending=data.pop('pending_revision_message_id',None)
            for message in data['messages']:
                if message['id']==pending:
                    message['revision_status']='applied'
                    for result in message.get('request_results',[]):
                        if result['status']=='pending':result['status']='updated'
            data.pop('last_message_input',None)
        if usage:data['messages'].append({'id':db.uid(),'role':'assistant','text':summary,'usage':usage,'created_at':db.now()})
    mutate(user,id,version,change)
    return state(user,id)

async def build(user,id,version,mode,decisions=None,template='education',feedback=None,manual=False,preparation=None,skip_questions=False):
    task_progress.stage('preparing')
    data=require(user,id,'resume_conversation')['data']
    if data['version']!=version:raise HTTPException(409,'Reload the conversation before building.')
    if not manual and not feedback:
        questions=profile_answers.stable_questions(data,'resume')
        open_ids=[q['id'] for q in questions if q.get('status')=='open']
        pending=any(p.get('status')=='pending' for p in data.get('proposals',[]))
        if (open_ids or pending) and not skip_questions:
            def wait(d,c):
                d['optimization_waiting']={'mode':mode,'template':template,'decisions':decisions or []}
            mutate(user,id,version,wait)
            return state(user,id)
        if skip_questions and open_ids:
            def skip(d,c):
                for q in profile_answers.stable_questions(d,'resume'):
                    if q['id'] in open_ids:q['status']='skipped'
                profile_answers.sync_questions(d,'resume')
            record=mutate(user,id,version,skip);data=record['data'];version=data['version']
        if pending:raise HTTPException(409,'Confirm or reject the pending Supporting Details before continuing.')

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
        if checked.get('schema_version')!=3 or checked.get('posting_hash')!=job_parser.posting_hash(posting):raise HTTPException(409,'Rerun the comparison for this posting before building an AI revision. The previous draft remains available.')
    prior=require(user,data['current_revision_id'],'resume_revision')['data'] if data.get('current_revision_id') else None
    placements=[]  # Explicit builds use current Profile relationships, not the retired placement gate.
    # Saved relationships are refreshed only by this explicit build, never by opening a draft.
    data={**data,'linked_project_placements':placements}
    if feedback is None and data.get('pending_feedback'):feedback=data['pending_feedback']
    token=db.uid();record=begin(user,id,version,token,preparation=prepared.model_dump() if prepared else None);version=record['data']['version'];data=record['data']
    current=require(user,data['current_revision_id'],'resume_revision')['data'] if data.get('current_revision_id') else None
    comparison_usage=None
    if data['profile_dirty'] and not manual:
        # The explicit optimization consumes fresh confirmed evidence. Comparison
        # remains a separate user action; do not start a hidden paid comparison.
        record=mutate(user,id,version,lambda d,c:d.update({'profile_dirty':False}))
        version=record['data']['version'];data=record['data']
    # Suggested edits refer to their original analysis. Approved facts append rather than replace source text.
    snapshot=source(user,{**data,'linked_project_placements':placements},decisions if not data['profile_dirty'] and not comparison_usage else [],(feedback or {}).get('template') if (feedback or {}).get('template') in ('education','experience') else current['snapshot']['template'] if current else template)
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
    feedback={'fit_one_page':data.get('one_page_requested',False),**(feedback or {}),'approved_record_ids':data['approved_record_ids']}
    feedback['user_constraints']=copy.deepcopy(data.get('user_constraints',{}))
    feedback['user_messages']=([m['text'] for m in data.get('messages',[]) if m['role']=='user'][-30:] if not current or feedback.get('refresh_linked_evidence') else [])
    # Ordinary refinements receive sanitized actionable instructions only. The
    # classifier's raw mixed batch stays in history, outside the writing prompt.
    if current and (feedback.get('refresh_linked_evidence') or not current['snapshot'].get('automatic_linked_evidence')):
        affected=[e['source_id'] for s in snapshot['sections'] for e in s['entries'] if feedback.get('refresh_linked_evidence') or e['category']=='project' or any(i.get('project_source') for i in e['content_items'])]
        feedback.update(change_selection=True,target_record_ids=affected)
        if feedback.get('refresh_linked_evidence'):
            feedback['target_item_ids']=[i['item_id'] for s in snapshot['sections'] for e in s['entries'] for i in e['content_items'] if i['field'] in linked_project_evidence.NARRATIVE]
            feedback['revision_instruction']='Re-evaluate the full confirmed Profile and its linked evidence for this posting. Select the strongest supported points yourself; the user does not need to choose bullets. Preserve factual and role boundaries.'
    if prepared and prepared.headline is not None and prepared.headline!=db.settings(user).get('headline',''):feedback['prepared_headline']=prepared.headline
    draft=await optimization.create(user,snapshot,analysis,mode,feedback,guided=True,current=current['snapshot'] if current else None)
    result=draft['data'];rendered=result['rendered_snapshot'];rendered['draft_id']=draft['id']
    if current and 'quality_review' not in result and current['snapshot'].get('optimization',{}).get('quality_review'):
        result['quality_review']=copy.deepcopy(current['snapshot']['optimization']['quality_review'])
    rendered['optimization']={k:result.get(k) for k in ('ai','audit_ai','planning_ai','editorial_ai','actual_cost_usd','headline_evidence','keywords','source_checked','strategy','user_constraints','quality_review')}
    usage={k:result.get(k) for k in ('ai','audit_ai','planning_ai','editorial_ai','layout_ai','quality_ai','repair_ai','actual_cost_usd')};usage['comparison_ai']=comparison_usage
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
        summary=' '.join(changes) or ('Completed full optimization; the draft content was preserved. See Resume quality review for the review outcome.' if feedback.get('refresh_linked_evidence') else 'The draft wording was preserved. This refinement did not run an independent quality review.')
    updated=save_revision(user,id,version,rendered,result['catalog'],summary,token,usage,snapshot,draft['id'])
    return updated

def request_items(text):
    marker=re.compile(r'^\s*(?:[•●▪*-]|\d+[.)])\s*(.*)$')
    items=[]
    for line in text.splitlines():
        match=marker.match(line)
        if match:
            if match.group(1).strip():items.append(match.group(1).strip())
        elif line.strip():
            if items:items[-1]+='\n'+line.strip()
            else:items.append(line.strip())
    if len(items)>40:raise ServiceError('Send up to 40 requests together.')
    return [{'request_id':'R'+str(n+1),'text':value} for n,value in enumerate(items)]


def request_results(output,items,proposals):
    supplied=output.get('request_results',[])
    if supplied:
        if {r['request_id'] for r in supplied}!={r['request_id'] for r in items} or len(supplied)!=len(items):raise ServiceError('The response did not account for each request. Your previous draft remains intact.')
    elif len(items)>1:raise ServiceError('The response did not account for each request. Your message is saved.')
    else:
        supplied=[{'request_id':items[0]['request_id'],'status':'awaiting_approval' if proposals else 'updated' if output['action']=='revise' else 'needs_clarification','explanation':output['message'],'instruction':output.get('revision_instruction','')}]
    results=copy.deepcopy(supplied);by_id={r['request_id']:r['text'] for r in items}
    for r in results:
        r['text']=by_id[r['request_id']]
        # A request containing new facts cannot also be dispatched as writing instructions.
        if any(any((f.get('value',f['user_quote']) in r['text'] or f['user_quote'] in r['text']) for f in p['fields']) for p in proposals):
            r.update(status='awaiting_approval',instruction='')
        if r['status']=='updated' and not r['instruction'].strip():r.update(status='not_applied',explanation='No actionable wording instruction was supplied.')
    active=[r for r in results if r['status']=='updated']
    for r in active:
        # Compatibility for old single-action interpreters. New typed results
        # always carry their own scope, including explicit false/empty values.
        for key,default in [('target_item_ids',[]),('target_record_ids',[]),('change_headline',False),('change_selection',False),('template','unchanged')]:
            r.setdefault(key,output.get(key,default) if len(active)==1 else default)
    orders={r.get('template') for r in active if r.get('template') in ('education','experience')}
    if len(orders)>1:
        for r in active:
            if r.get('template') in orders:r.update(status='needs_clarification',instruction='',explanation='Choose one section order; these requests conflict.')
    return results


def actionable_feedback(output,results):
    active=[r for r in results if r['status']=='updated']
    output['target_item_ids']=list(dict.fromkeys(i for r in active for i in r.get('target_item_ids',[])))
    output['target_record_ids']=list(dict.fromkeys(i for r in active for i in r.get('target_record_ids',[])))
    output['change_headline']=any(r.get('change_headline') for r in active)
    output['change_selection']=any(r.get('change_selection') for r in active)
    output['template']=next((r['template'] for r in active if r.get('template') in ('education','experience')),'unchanged')
    output['revision_instruction']='\n'.join(r['instruction'] for r in active)
    return output


async def send(user,id,body):
    items=request_items(body.text)
    if not items:raise ServiceError('Write at least one request; empty bullet markers are not a request.')
    record=begin(user,id,body.expected_version,message=body.text);data=record['data'];version=data['version']
    records=profile_answers.records(user);current=require(user,data['current_revision_id'],'resume_revision')['data'] if data.get('current_revision_id') else None
    job=require(user,data['job_id'],'job');criteria=job_parser.criteria(job['data'])+role_alignment.catalog(job['data'])
    analysis=(db.get(user,data.get('analysis_id'),'analysis') or {}).get('data',{})
    materials=project_sources.context(user,data)
    task_progress.stage('reviewing')
    output,meta=await ai.structured(ResumeChatOutput,{'task':'''Continue a focused resume conversation. Consider saved project analyses automatically, but only as context for posting-specific questions, never confirmed applicant facts. Put project-specific follow-ups in project_questions with exact project_context_ids from that context; put only other questions in questions. Reuse already confirmed answers and ask at most three questions total. Ask concrete, nonrepeated questions about actual contributions, audience, methods or outcomes; explain relevance. Never ask for invented metrics. Distinguish facts from wording/layout instructions. New factual details must be proposals, NEVER used in a revision before explicit human approval. Each field value must be an EXACT contiguous excerpt of the latest user message, with user_quote containing it. For narrative fields only (description, contribution, accomplishments), also provide suggested_value as polished professional wording: fix grammar, remove repetition, organize actions, methods and supported outcomes. Expand only explanations already supported by that exact quote. Never invent tools, numbers, outcomes, validation success or personal ownership. Preserve uncertainty, incomplete work, team boundaries and intent versus measured results. Keep raw value and user_quote unchanged. Provide an editing_note explaining changes and up to three optional improvement_suggestions asking for useful missing details; never insert those missing details as facts. Do not polish structured or private authorization fields. Use an existing record_id only for the same role/project; empty record_id creates a separate record. Allowed narrative fields: description, contribution, accomplishments, tools, relevant_courses, honors; structured fields use the supplied Profile schema. Authorization is category authorization, fields us_citizen/authorized_us/sponsorship_now/sponsorship_future with yes/no/unsure values. Citizenship is distinct from work authorization. Direct eligibility questions to private Profile settings; do not ask them in the professional-experience question group. No proposals for ordinary shortening/emphasis/layout requests. For actionable wording feedback action=revise, identify exact target item and record IDs; preserve unrelated text/selection. Set change_selection only when requested; change_headline only when requested. Set template=education or experience only if the user requests that section ordering; otherwise unchanged. A question-only response action=question leaves draft unchanged. Do not repeat questions already asked. revision_instruction contains only wording/layout instructions, never unapproved factual assertions.''','unreviewed_project_material_for_questions_only':materials,'submitted_question_answers':body.question_answers,'latest_user_message':body.text,'request_items':items,'batch_rules':'Account for EVERY request_id exactly once in request_results. updated means an actionable supported wording/layout instruction, already_satisfied needs no change, awaiting_approval contains new facts, needs_clarification includes conflicting/ambiguous requests, not_applied explains a blocked change. Supply sanitized instruction and its exact target_item_ids, target_record_ids, change_headline, change_selection and template scope only for updated requests. Each request scope must describe only that individual change; deferred requests have empty/false/unchanged scope. Never include unapproved facts or conflicting instructions. Compatible edits may proceed even when another request requires factual approval. Do not mark a request updated merely for acknowledging it.','messages':data['messages'][-30:],'previous_questions':data.get('asked_questions',data['questions']),'proposals':data['proposals'],'criterion_catalog':criteria,'duty_alignment':role_alignment.rows(analysis,job['data']),'question_rules':'Use unresolved duty and qualification evidence to ask specific nonrepeated questions. Ask what the user personally did, how, for whom, and what outcome is supported. Already reviewed stories are in confirmed_profile. Reuse facts already present there; do not propose duplicate copies as new facts. Never infer a lack of experience; never ask for invented metrics or external research.','confirmed_profile':[{'id':r['id'],'data':r['data']} for r in records if r['data'].get('confirmed')],'current_draft':public(current),'profile_fields':list(ExperienceItem.model_fields)},body.mode,retry_allowed=False)
    allowed_records={r['id']:r for r in records};criterion_ids={r['id'] for r in criteria}
    known_items={i['item_id'] for r in (current or {}).get('catalog',[]) for i in r['items']}
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
        item={**proposal,'id':db.uid(),'status':'pending','source_message_id':data['messages'][-1]['id'],'expected_updated_at':old['updated_at'] if old else None,'original':(db.get(user,old['id'],'experience') or old)['data'] if old else {k:v for k,v in db.settings(user).items() if k in ('us_citizen','authorized_us','sponsorship_now','sponsorship_future')} if private else None}
        profile_answers.associate_inputs(data,item,'resume',body.question_answers)
        project_context.bind_proposal(user,data,item,'resume')
        proposals.append(item)
    project_questions=[{'text':q['text'],'reason':'Clarify this project for the posting','criterion_id':None,'project_refs':project_context.references(q['project_context_ids'],materials)} for q in output.get('project_questions',[])]
    results=request_results(output,items,proposals)
    actionable_feedback(output,results)
    if set(output['target_item_ids'])-known_items or set(output['target_record_ids'])-set(allowed_records):raise ServiceError('The feedback referred to unavailable content. Your message is saved; retry with the item name.')
    actionable=[r for r in results if r['status']=='updated']
    revising=bool(current and actionable)
    if not current:
        for r in actionable:r.update(status='not_applied',explanation='Build a first draft before requesting wording changes.')
    output['revision_instruction']='\n'.join(r['instruction'] for r in actionable)
    for r in results:
        if revising and r['status']=='updated':r['status']='pending'
    output['fit_one_page']=resume_layout.one_page_request(output['revision_instruction']) or data.get('one_page_requested',False)
    assistant_id=db.uid()
    def append(d,c):
        d['messages'].append({'id':assistant_id,'role':'assistant','text':output['message'],'created_at':db.now(),'request_results':results,'usage':{'ai':meta,'actual_cost_usd':meta.get('estimated_token_cost_usd')},**({'revision_status':'pending'} if revising else {})})
        if revising:d['pending_revision_message_id']=assistant_id
        if output['fit_one_page']:d['one_page_requested']=True
        seen={q['text'].strip().casefold() for q in d.get('asked_questions',d['questions'])}
        new=[{'text':q,'reason':'Improve the resume evidence','criterion_id':None} for q in output['questions'] if q.strip().casefold() not in seen]
        new.extend(q for q in project_questions if q['text'].strip().casefold() not in seen)
        new=project_context.fresh_questions(user,new)[:3]
        d['questions']=new;d.setdefault('asked_questions',[]).extend(new)
        d['proposals']+=proposals;d.pop('last_message_input',None)
        if revising and output.get('revision_instruction'):
            constraints=d.setdefault('user_constraints',{})
            constraints.setdefault('instructions',[]).append({'instruction':output['revision_instruction'],'user_quote':'\n'.join(r['text'] for r in actionable),'message_id':d['messages'][-2]['id']})
            constraints['instructions']=constraints['instructions'][-20:]
        if proposals or revising:d['pending_feedback']={k:output.get(k) for k in ('revision_instruction','target_item_ids','target_record_ids','change_headline','change_selection','template','fit_one_page')}
    updated=mutate(user,id,version,append)
    if revising:
        try:return await build(user,id,updated['data']['version'],body.mode,feedback={k:output.get(k) for k in ('revision_instruction','target_item_ids','target_record_ids','change_headline','change_selection','template','fit_one_page')})
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
                            if message['id']==assistant_id:
                                message['revision_status']='failed'
                                for result in message.get('request_results',[]):
                                    if result['status']=='pending':result.update(status='not_applied',explanation='The revision did not save. The previous PDF is still current.')
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
        if body.keep_standalone:raise HTTPException(422,'Choose a related project; standalone Supporting Details are no longer supported.')
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
            links=profile_answers.validate_links(c,user,body.experience_ids) if body.experience_ids is not None else []
            selected_project=next((id for id in links if profile_answers.owned_experience(c,user,id)['data']['category']=='project'),'')
            target=project_context.destination(c,user,proposal,selected_project or body.evidence_experience_id,body.evidence_expected_updated_at,body.keep_standalone)
            rid=target['id'] if target else '';proposal['applied_record_id']=rid;proposal['category']='project';proposal['experience_ids']=[rid]+[link for link in links if link!=rid]
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
                if row:
                    e['content_items']=copy.deepcopy(row['items']);e['bullets']=[i['text'] for i in row['items']]
                    if 'resume_order' in row:e['resume_order']=row['resume_order']
    rows=resume_builder.catalog(full);available={r['id'] for r in rows}
    if set(body.resume.experience_ids)-available:raise HTTPException(400,'Select only content from this revision.')
    full=optimization.apply(full,{'entries':[],'headline':body.resume.headline if body.resume.headline is not None else (current['snapshot']['headline'] if current else full['headline'])},body.resume.overrides)
    if current:
        saved_constraints=copy.deepcopy(data.get('user_constraints',{}))
        if body.resume.headline is not None:saved_constraints['headline']=body.resume.headline
        locks=saved_constraints.setdefault('locked_items',{})
        for e in linked_project_evidence.entries(full).values():
            for item in e['content_items']:
                if item['item_id'] in body.resume.overrides:
                    item['user_locked']=True
                    locks[item['item_id']]={'text':item['text'],'record_id':e['source_id'],'source_ids':[r['source_id'] for r in item.get('source_refs',[])]}
    full['decisions']=[d.model_dump() for d in body.resume.decisions]
    full['template']=body.resume.template
    full['compact_skills']=body.resume.compact_skills
    full['separate_certifications']=True
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
    if current:
        before_sources={r['source_id'] for e in linked_project_evidence.entries(current['snapshot']).values() for i in e['content_items'] for r in i.get('source_refs',[])}
        after_sources={r['source_id'] for e in linked_project_evidence.entries(selected).values() for i in e['content_items'] for r in i.get('source_refs',[])}
        excluded=(set(saved_constraints.get('excluded_source_ids',[]))|before_sources-after_sources)-after_sources
        saved_constraints['excluded_source_ids']=sorted(excluded)
        saved_constraints['locked_items']={key:value for key,value in saved_constraints['locked_items'].items() if not set(value.get('source_ids',[]))&excluded}
        selected.setdefault('optimization',{})['user_constraints']=saved_constraints
    rendered=resume_layout.render(selected)
    if rendered.get('optimization',{}).get('strategy'):
        from . import resume_strategy
        prior=rendered['optimization']['strategy'];rendered['optimization']['strategy']={**prior,'priorities':resume_strategy.coverage(prior,rendered)}
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
        if resume_quality.acknowledgment_required(snapshot) and not body.quality_warning_acknowledged:raise HTTPException(409,'Acknowledge the quality warning for this exact revision before saving. Review the specific changes still needed.')
        if snapshot['layout']['pages']!=1 or not snapshot['layout']['validated']:raise HTTPException(409,'Shorten this draft to one page before saving employer downloads.')
        saved=value.get('finalized_resume_id')
        if not saved:
            snapshot.update({'conversation_id':id,'revision_id':revision['id'],'title':resume_data.resume_title(snapshot.get('posting_snapshot'),snapshot.get('title') or 'Resume',snapshot.get('name') or '')})
            snapshot['quality_warning_acknowledged']=bool(body.quality_warning_acknowledged)
            saved=write(c,user,'resume',snapshot);value['finalized_resume_id']=saved;write(c,user,'resume_revision',value,revision['id'])
        data['last_saved_resume_id']=saved
    record=mutate(user,id,body.expected_version,change)
    saved=require(user,record['data']['last_saved_resume_id'],'resume');applications.attach_resume(user,saved)
    return state(user,id)

def estimate(user,id,mode,settings=None):
    data=require(user,id,'resume_conversation')['data'];snapshot=source(user,data)
    from . import document_models
    settings=settings if settings is not None else db.settings(user)
    base=optimization.estimate(snapshot,mode,settings);option=document_models.options(settings,mode)
    current=db.get(user,data.get('current_revision_id',''),'resume_revision') if data.get('current_revision_id') else None
    context_size=len(json.dumps(snapshot))+len(json.dumps(data['messages'][-30:]))+len(json.dumps(data['proposals']))+len(json.dumps(public(current)))
    extra=ai_settings.estimate(option['model'],option['reasoning_effort'],max(3000,context_size//4)+7000,4500,service_tier=option['service_tier'],max_output_tokens=settings.get('ai_max_output_tokens') or None)
    # Reserve one layout pass plus chat; approved new facts also require reassessment.
    multiplier=2 if data['profile_dirty'] else 1
    base['usd']=round(base['usd']+extra['usd']*multiplier,6) if base['usd'] is not None and extra['usd'] is not None else None
    base['note']='Planning estimate for chat, evidence strategy, drafting, final source/coverage check, editorial and isolated quality reviews, one optional repair, one measured layout correction and a blinded comparison (up to eight optimization requests). Approved facts may add a comparison refresh. No automatic paid retries. A question-only reply costs less; actual usage is shown afterward. Local previews, saving and downloads make no provider requests.'
    return base


def adopt(user,id,body):
    data=require(user,id,'resume_conversation')['data'];draft=require(user,body.draft_id,'resume_draft')['data']
    if draft['job_id']!=data['job_id']:raise HTTPException(409,'That draft belongs to another posting.')
    snapshot=source(user,data)
    if draft.get('source_fingerprint')!=optimization.fingerprint(snapshot):raise HTTPException(409,'The Profile changed since this historical draft. Its wording remains available, but build a fresh draft to use current sources.')
    if draft.get('posting_hash')!=job_parser.posting_hash(snapshot['posting_snapshot']):raise HTTPException(409,'The posting changed since this historical draft. Build a fresh draft for the current posting.')
    for section in snapshot['sections']:
        for entry in section['entries']:
            for n,item in enumerate(entry['content_items']):
                item['text']=draft.get('baseline',{}).get(item['item_id'],item['text']);entry['bullets'][n]=item['text']
    token=db.uid();record=begin(user,id,body.expected_version,token)
    proposal=optimization.apply(snapshot,draft)
    rendered=resume_layout.render(resume_builder.select(proposal,draft['content'],draft['experience_ids']))
    rendered['optimization']={k:draft.get(k) for k in ('ai','audit_ai','planning_ai','editorial_ai','actual_cost_usd','headline_evidence','keywords','source_checked','strategy','user_constraints','quality_review')}
    return save_revision(user,id,record['data']['version'],rendered,resume_builder.catalog(proposal),'Opened a historical AI draft as a new working revision. Review its current PDF before saving.',token,source_snapshot=snapshot,draft_id=body.draft_id)


def place_project_evidence(user,id,body):
    """Explicit local placement review. Immutable prior revision and Profile stay intact."""
    record=require(user,id,'resume_conversation');data=record['data']
    if data['version']!=body.expected_version:raise HTTPException(409,'This draft changed. Reload it before applying linked evidence. Your choices are retained.')
    if data.get('workspace_request'):raise HTTPException(409,'Finish rendering or restore your local edits before applying linked evidence.')
    with db.connect() as c:
        if task_running(c,user,id):
            # The endpoint's own local task is running; reject other request types via workspace token/version below.
            active=[json.loads(r['result'] or '{}').get('inputs',{}) for r in c.execute("SELECT result FROM tasks WHERE user_id=? AND kind='resume_guided' AND status IN ('queued','running')",(user,))]
            if any(v.get('conversation_id')==id and 'placements' not in v for v in active):raise HTTPException(409,'Wait for the current resume request before changing placements.')
    reviewed=linked_project_evidence.checked(user,body.placements)
    current=require(user,data['current_revision_id'],'resume_revision')['data'] if data.get('current_revision_id') else None
    choices=[c for c,r in reviewed]
    if not current:
        def save(d,c):d['linked_project_placements']=choices
        mutate(user,id,body.expected_version,save)
        return state(user,id)
    full=copy.deepcopy(current['source_snapshot'])
    # Restore all local catalog rewrites before moving source items.
    old_rows={r['id']:r for r in current['catalog']}
    for rid,entry in linked_project_evidence.entries(full).items():
        if rid in old_rows:entry['content_items']=copy.deepcopy(old_rows[rid]['items']);linked_project_evidence.sync(entry)
    old_selected={}
    for rid,entry in linked_project_evidence.entries(current['snapshot']).items():
        for item in entry['content_items']:
            ref=item.get('project_source')
            old_selected[(ref['project_id'],ref['item_id']) if ref else (rid,item['item_id'])]=True
    full=linked_project_evidence.apply(full,reviewed)
    explicit={(r['project_id'],r['item_id']):c for c,r in reviewed}
    parts={};ids=[]
    for rid,entry in linked_project_evidence.entries(full).items():
        chosen=[]
        for n,item in enumerate(entry['content_items']):
            ref=item.get('project_source');key=(ref['project_id'],ref['item_id']) if ref else (rid,item['item_id'])
            # Explicit placements include the reviewed detail; all unrelated selection is retained.
            if (key in explicit and explicit[key]['placement']!='omit') or key in old_selected:chosen.append(n)
        parts[rid]=chosen
        if chosen or (entry['category']=='education' and rid in current['snapshot']['experience_ids']):ids.append(rid)
    selected=resume_builder.select(full,parts,ids)
    task_progress.stage('rendering');rendered=resume_layout.render(selected)
    # Render first: failures never move the head or erase the current PDF.
    linked_project_evidence.checked(user,choices)  # Recheck sources after potentially slow local rendering.
    token=db.uid();record=begin(user,id,body.expected_version,token)
    return save_revision(user,id,record['data']['version'],rendered,resume_builder.catalog(full),'Applied reviewed linked-project placements. No AI request. Review the updated PDF before saving.',token,source_snapshot=full,draft_id=None)


def quality_estimate(user,id,mode):
    data=require(user,id,'resume_conversation')['data']
    if not data.get('current_revision_id'):raise HTTPException(409,'Build a draft before reviewing quality.')
    revision=require(user,data['current_revision_id'],'resume_revision')['data']
    return resume_quality.estimate(revision['snapshot'],mode,db.settings(user))


async def recheck_quality(user,id,body):
    from . import personalization,resume_strategy
    data=require(user,id,'resume_conversation')['data']
    if data['version']!=body.expected_version or data.get('current_revision_id')!=body.revision_id:raise HTTPException(409,'Review the current revision before rechecking quality.')
    if data.get('workspace_request'):raise HTTPException(409,'Render the pending edits before rechecking quality.')
    revision=require(user,body.revision_id,'resume_revision')['data']
    if revision['conversation_id']!=id:raise HTTPException(409,'Choose a revision from this conversation.')
    snapshot=copy.deepcopy(revision['snapshot']);before=source(user,data)
    if job_parser.posting_hash(before['posting_snapshot'])!=job_parser.posting_hash(snapshot['posting_snapshot']):raise HTTPException(409,'The posting changed. Optimize for the current posting before rechecking.')
    signature=resume_strategy.signature(before);privacy=personalization.request_version(user)
    record=begin(user,id,body.expected_version,body.request_token)
    review=None;usage=[];note=''
    try:
        review,meta=await resume_quality.review(snapshot,body.mode);usage.append(meta)
    except ServiceError as exc:note='Quality review unavailable: '+str(exc)
    personalization.check_request(user,privacy)
    fresh=source(user,data)
    if resume_strategy.signature(fresh)!=signature or job_parser.posting_hash(fresh['posting_snapshot'])!=job_parser.posting_hash(snapshot['posting_snapshot']):raise ServiceError('Sources changed during quality review; the previous revision remains intact.')
    snapshot.setdefault('optimization',{})['quality_review']=resume_quality.stamp(snapshot,review,usage,note)
    cost=sum(m.get('estimated_token_cost_usd') or 0 for m in usage) if usage and all(m.get('estimated_token_cost_usd') is not None for m in usage) else None
    return save_revision(user,id,record['data']['version'],snapshot,revision['catalog'],'Rechecked draft quality. Document bytes and factual-validation status are unchanged.',body.request_token,{'quality_ai':usage,'actual_cost_usd':cost},revision.get('source_snapshot'),revision.get('draft_id'),quality_only=True)
