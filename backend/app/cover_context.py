from . import task_progress
"""Question-led collection and explicit review of letter-specific evidence."""
from . import project_sources,project_context
import copy
import re
from fastapi import HTTPException
from . import ai,db,guidance,cover_letters as letters,profile_answers
from .models import CoverQuestionsOutput,CoverChatOutput,CoverContent,ExperienceItem,CoverPolishOutput
from .network import ServiceError

PRIVATE=r'\b(citizen(?:ship)?|sponsorship|visa status|work authorization|authori[sz]ed to work)\b'
LOGISTICS=r'\b(availability|available to work|onsite|on-site|rising senior|enrollment eligibility|sponsorship|citizenship|work authorization)\b'

EDITING='''For every new detail, keep user_quote as an EXACT contiguous excerpt, but write suggested_text as polished, useful professional wording, not a transcription. Fix grammar, remove repetition, organize the applicant's action, method and supported outcome; expand only to explain facts already present in that excerpt. Preserve uncertainty, unfinished work, team boundaries, computing limits and intent versus measured success. Never add tools, metrics, validation claims, causality or accomplishments. Do not strengthen "aimed to improve" into "improved". editing_note briefly explains the wording changes and retained limits. improvement_suggestions contains up to three optional, specific questions that could strengthen the story IF the user knows the answer. Missing information stays in these suggestions, never in suggested_text. Keep motivation personal and scoped to this opportunity. All suggested wording is unreviewed until explicit approval.'''

def checked_suggestion(detail,quote):
    text=(detail.get('suggested_text') or quote).strip()
    if not text or re.search(PRIVATE,text,re.I) or ai.numeric_facts(text)-ai.numeric_facts(quote):raise ServiceError('The wording suggestion introduced unsupported details. Your original answer and pending review are preserved.')
    return text

async def polish(user,id,body):
    """Explicit re-edit of pending legacy proposals through the existing message task."""
    data=letters.require(user,id,'cover_workspace')['data'];ids=body.polish_proposal_ids
    pending={p['id']:p for p in data.get('context_proposals',[]) if p['status']=='pending'}
    if len(set(ids))!=len(ids) or set(ids)-set(pending):raise HTTPException(400,'Choose pending details from this letter to improve.')
    for pid in ids:profile_answers.check_fresh(data,pending[pid],'cover')
    task_progress.stage('reviewing')
    workspace,_=active_request(user,id,body);data=workspace['data']
    output,meta=await ai.structured(CoverPolishOutput,{'task':'Polish these pending details for human review; do not approve facts or draft a letter. '+EDITING,'details':[{'proposal_id':pid,'kind':pending[pid]['kind'],'user_quote':pending[pid]['user_quote'],'current_wording':pending[pid]['text']} for pid in ids]},body.mode,instructions=letters.INSTRUCTIONS,retry_allowed=False)
    edited={d['proposal_id']:d for d in output['details']}
    if len(edited)!=len(output['details']) or set(edited)!=set(ids):raise ServiceError('The wording review referred to different details. Your review is preserved.')
    for pid,detail in edited.items():checked_suggestion(detail,pending[pid]['user_quote'])
    def change(current,c):
        for proposal in current['context_proposals']:
            if proposal['id'] not in edited:continue
            if proposal['status']!='pending':raise HTTPException(409,'A detail was already reviewed. Reload before editing it.')
            profile_answers.check_fresh(current,proposal,'cover')
            proposal.setdefault('wording_history',[]).append({k:copy.deepcopy(proposal[k]) for k in ('suggested_text','editing_note','improvement_suggestions') if k in proposal})
            proposal.update({k:v for k,v in edited[proposal['id']].items() if k!='proposal_id'})
        current.setdefault('messages',[]).append(message('Prepared wording suggestions. Review or edit them before approval; your original answers remain saved.',usage(meta)))
    letters.mutate(user,id,data['version'],change)
    return letters.state(user,id)

def defaults(data):
    for name in ('questions','context_proposals'):data.setdefault(name,[])
    data.setdefault('context_dirty',False)

def approved(data):
    from .cover_goals import active_proposals
    return [copy.deepcopy(p) for p in active_proposals(data) if p['status']=='approved']

def active_request(user,id,body):
    """Retain inputs without invalidating an unchanged rendered letter for a question."""
    return letters.begin(user,id,body,preserve_preview=True)

def quote_text(posting):return '\n'.join(v for v in posting.values() if isinstance(v,str))

def make_questions(rows,data,guide,materials=None):
    allowed={r['id'] for r in letters.sources(data)};guide_ids={r['id'] for r in guide['items']}
    seen={ai.normalized(q['text']) for q in data.get('questions',[])};result=[]
    for q in rows:
        if set(q['source_ids'])-allowed or set(q['guidance_ids'])-guide_ids:raise ServiceError('A question referred to unavailable sources. Your previous letter is preserved.')
        if q['job_quote'] and not ai.valid_quote(q['job_quote'],quote_text(data['posting_snapshot'])):raise ServiceError('A question could not be traced to the posting.')
        if re.search(LOGISTICS,q['text'],re.I):raise ServiceError('The questions included an eligibility or logistics checklist. Retry to focus on the letter.')
        normalized=ai.normalized(q['text'])
        if normalized in seen:continue
        seen.add(normalized);result.append({**q,'project_refs':project_context.references(q.get('project_context_ids',[]),materials or []),'id':db.uid(),'status':'open','created_at':db.now(),'writing_guidance':{'version':guide['version'],'items':[copy.deepcopy(g) for g in guide['items'] if g['id'] in q['guidance_ids']]}})
    return result

def message(text,usage=None):
    return {'id':db.uid(),'role':'assistant','text':text,'created_at':db.now(),'usage':usage}

def usage(meta):return {'ai':meta,'actual_cost_usd':meta.get('estimated_token_cost_usd')}

async def sync_preview(user,id,body):
    state=letters.state(user,id)
    if state['preview_stale'] and any(p.strip() for p in body.content.paragraphs):
        return await letters.render(user,id,body.model_copy(update={'expected_version':state['data']['version'],'text':''}))
    return state

async def prepare(user,id,body):
    task_progress.stage('questions')
    workspace,_=active_request(user,id,body);data=workspace['data'];defaults(data)
    if any(q['status']=='open' for q in data['questions']):return await sync_preview(user,id,body)
    guide=guidance.selected('cover')
    materials=project_sources.context(user,data)
    output,meta=await ai.structured(CoverQuestionsOutput,{'task':'''Prepare up to three concise, specific questions BEFORE writing a cover letter. Analyze the exact posting and selected saved resume using the curated writing principles. Ask about genuine motivation, the story behind one or two useful examples, individual decisions/contributions, a challenge, audience or supported outcome that the resume leaves unexplained. Explain how each answer could improve THIS letter. Do not ask a generic skill checklist, eligibility/enrollment/work authorization, location, schedule or availability questions. Do not demand invented metrics. Avoid questions already answered, skipped or asked; use conversation and reviewed context. Never assume motivation, company culture, or applicant facts. Each question has source_ids from the saved resume/reviewed answers as relevant, an exact job_quote if applicable, and relevant guidance_ids. Guidance is advice, NEVER applicant evidence. If existing context is sufficient, return no questions and explain that the user can build. Automatically consider relevant saved project summaries and findings for questions only. Project observations never establish personal work. Use project_context_ids for materials behind each question. Reuse confirmed_professional_answers before asking. Do not draft the letter.''','unreviewed_project_material_for_questions_only':materials,'confirmed_professional_answers':[{'id':r['id'],'title':r['data']['title'],'text':r['data']['text'],'experience_id':r['data'].get('experience_id',''),'experience_ids':profile_answers.experience_ids(r['data']),'questions':[q['text'] for source in r['data'].get('sources',[]) for q in source.get('questions',[])]} for r in profile_answers.confirmed(user) if r['data']['answer_kind']=='experience'],'posting':data['posting_snapshot'],'saved_resume_sources':letters.sources(data),'questions_already_asked':data['questions'],'conversation':data.get('messages',[])[-24:],'reviewed_context':approved(data),'writing_guidance':guide},body.mode,instructions=letters.INSTRUCTIONS,retry_allowed=False)
    questions=project_context.fresh_questions(user,make_questions(output['questions'],data,guide,materials))
    def change(current,c):
        defaults(current);current['questions'].extend(questions);current['question_guidance']=guide
        current.setdefault('messages',[]).append({**message(output['message'],usage(meta)),'writing_guidance':guide})
    letters.mutate(user,id,data['version'],change)
    return await sync_preview(user,id,body)

def skip(user,id,body):
    def change(data,c):
        defaults(data);known={q['id']:q for q in data['questions']}
        if set(body.question_ids)-set(known):raise HTTPException(400,'Choose questions from this letter.')
        for qid in body.question_ids:
            if known[qid]['status']=='open':known[qid]['status']='skipped'
    letters.mutate(user,id,body.expected_version,change)
    return letters.state(user,id)

async def send(user,id,body):
    if body.polish_proposal_ids:return await polish(user,id,body)
    task_progress.stage('reviewing')
    workspace,token=active_request(user,id,body);data=workspace['data'];defaults(data);guide=guidance.selected('cover');materials=project_sources.context(user,data)
    output,meta=await ai.structured(CoverChatOutput,{'task':'''Continue a question-led cover-letter conversation. The applicant may answer any or all prepared questions, give new personal motivation/experience, ask a question or request a wording/layout change. For new applicant facts or motivation, action=collect and return details with EXACT contiguous user_quote excerpts from the latest message. Never use these details in employer text before explicit human review. Separate motivation from professional experience. Use related_source_id only when clearly about a supplied resume example; new roles/projects may leave it empty. supersedes_id may refer to an existing approved context item only when the user corrects it. Do not treat posting requirements, guidance examples, employer claims or hypothetical suggestions as applicant facts. Unsupported company claims need a source and must not become experience proposals. Private authorization belongs in Profile settings, not the letter. Mark only genuinely answered/skipped question IDs, and ask at most two helpful nonrepeated follow-ups only when clarification materially matters. Do not ask eligibility, scheduling or availability questions. Ordinary wording/layout requests need no proposals. action=revise identifies zero-based paragraph_indices; set revise_all=true only for an explicitly whole-letter change or no draft. Preserve unrelated wording. action=reply answers advice/questions without changing the PDF. Header compact/full and subject show/hide are local format controls. revision_instruction contains wording instructions, never unapproved facts. Automatically use saved project analyses only to ask posting-specific followup_questions with their project_context_ids. Never treat artifacts as confirmed applicant facts, and reuse confirmed_professional_answers before asking. Advice uses the curated principles, which are not applicant evidence.'''+' '+EDITING,'submitted_question_answers':body.question_answers,'latest_user_message':body.text,'conversation':data.get('messages',[])[-24:],'questions':data['questions'],'reviewed_context':approved(data),'pending_details':[p for p in data['context_proposals'] if p['status']=='pending'],'saved_resume_sources':letters.sources(data),'unreviewed_project_material_for_questions_only':materials,'confirmed_professional_answers':[{'id':r['id'],'title':r['data']['title'],'text':r['data']['text'],'experience_id':r['data'].get('experience_id',''),'experience_ids':profile_answers.experience_ids(r['data']),'questions':[q['text'] for source in r['data'].get('sources',[]) for q in source.get('questions',[])]} for r in profile_answers.confirmed(user) if r['data']['answer_kind']=='experience'],'posting':data['posting_snapshot'],'current_letter':body.content.model_dump(),'writing_guidance':guide},body.mode,instructions=letters.INSTRUCTIONS,retry_allowed=False)
    known={q['id'] for q in data['questions']};answer_ids=set(output.get('answered_question_ids',[]));skip_ids=set(output.get('skipped_question_ids',[]))
    if (answer_ids|skip_ids)-known or answer_ids&skip_ids:raise ServiceError('The reply referred to an unavailable or conflicting question status. Your message is preserved.')
    rows={r['id']:r for r in letters.sources(data)};prior={p['id']:p for p in data['context_proposals']};proposals=[]
    for detail in output.get('details',[]):
        quote=detail['user_quote']
        if quote not in body.text or set(detail['question_ids'])-known:raise ServiceError('A proposed detail could not be traced to your message. Nothing was added to the letter.')
        if re.search(PRIVATE,quote,re.I):raise ServiceError('Authorization details belong in private Profile settings and cannot become letter evidence.')
        if detail['related_source_id'] and detail['related_source_id'] not in rows:raise ServiceError('A detail referred to unavailable resume content.')
        if detail['supersedes_id'] and (detail['supersedes_id'] not in prior or prior[detail['supersedes_id']]['status']!='approved'):raise ServiceError('A correction referred to unavailable reviewed context.')
        if any(p['status'] in ('pending','approved') and ai.normalized(p.get('user_quote',p['text']))==ai.normalized(quote) for p in data['context_proposals']+proposals):continue
        related=rows.get(detail['related_source_id'],{});matches=[r for r in db.list_entities(user,'experience') if r['data'].get('confirmed') and r['data']['title']==related.get('label')]
        target=matches[0] if len(matches)==1 else None
        proposals.append({**detail,'id':db.uid(),'status':'pending','text':checked_suggestion(detail,quote),'source_message_id':data['messages'][-1]['id'],'source_message_text':body.text,'created_at':db.now(),'profile_record_id':target['id'] if target else '', 'profile_expected_updated_at':target['updated_at'] if target else '', 'profile_original':copy.deepcopy(target['data']) if target else None})
    for proposal in proposals:
        profile_answers.associate_inputs(data,proposal,'cover',body.question_answers)
        project_context.bind_proposal(user,data,proposal,'cover')
    open_slots=max(0,3-sum(q['status']=='open' and q['id'] not in answer_ids|skip_ids for q in data['questions']))
    followups=project_context.fresh_questions(user,make_questions(output.get('followup_questions',[]),data,guide,materials))[:open_slots]
    def append(current,c):
        defaults(current)
        for q in current['questions']:
            if q['id'] in answer_ids:q['status']='answered'
            elif q['id'] in skip_ids:q['status']='skipped'
        current['questions'].extend(followups);current['context_proposals'].extend(proposals)
        current['question_guidance']=guide
        current.setdefault('messages',[]).append({**message(output['reply'],usage(meta)),'writing_guidance':guide})
        if proposals:
            feedback={k:output.get(k) for k in ('revision_instruction','paragraph_indices','revise_all')}
            if data.get('current_revision_id') and not feedback['paragraph_indices'] and not feedback['revise_all']:
                kinds={p['kind'] for p in proposals};feedback['paragraph_indices']=list(dict.fromkeys(([0] if 'motivation' in kinds else [])+([min(1,len(body.content.paragraphs)-1)] if 'experience' in kinds else [])))
            current['pending_context_feedback']=feedback
    workspace=letters.mutate(user,id,data['version'],append)
    if proposals or output['action']=='collect':return await sync_preview(user,id,body)
    modified=body.content.model_copy(deep=True)
    if output['header_style']!='unchanged':modified.header_style=output['header_style']
    if output['subject']!='unchanged':modified.show_subject=output['subject']=='show'
    format_only=(modified.header_style!=body.content.header_style or modified.show_subject!=body.content.show_subject) and not output['revise_all'] and not output['paragraph_indices']
    if output['action']=='revise' and not format_only and (output['revise_all'] or output['paragraph_indices'] or output['revision_instruction'].strip()):
        if any(p['status']=='pending' for p in workspace['data']['context_proposals']):raise ServiceError('Review or reject the pending details before an AI revision. Your previous letter remains available.')
        # The chat response was persisted above; draft adds a short completion message and its combined usage.
        next_body=body.model_copy(update={'expected_version':workspace['data']['version'],'content':modified,'text':''})
        workspace,token=letters.begin(user,id,next_body)
        return await letters.draft(user,workspace,token,next_body,output,meta)
    if modified!=body.content:
        return await letters.render(user,id,body.model_copy(update={'expected_version':workspace['data']['version'],'content':modified,'text':''}))
    return await sync_preview(user,id,body)

async def review(user,id,body):
    from . import cover_goals
    cover_goals.validate_current(user,letters.require(user,id,'cover_workspace')['data'])
    decisions={d.proposal_id:d for d in body.decisions}
    if len(decisions)!=len(body.decisions):raise HTTPException(400,'Review each detail once.')
    def change(data,c):
        defaults(data);proposals={p['id']:p for p in data['context_proposals']}
        if set(decisions)-set(proposals):raise HTTPException(400,'Choose details from this conversation.')
        profile_stamps={}
        for pid,decision in decisions.items():
            proposal=proposals[pid]
            profile_answers.check_fresh(data,proposal,'cover')
            if proposal['status']!='pending':
                if proposal['status']=='approved' and decision.action=='approve' and (decision.text or proposal['text']).strip()==proposal['text'] and decision.save_to_profile==proposal.get('save_to_profile',False) and (decision.experience_ids is None or decision.experience_ids==profile_answers.experience_ids(proposal)):continue
                if proposal['status']=='rejected' and decision.action=='reject':continue
                raise HTTPException(409,'This detail was already reviewed. Reload to use the current context.')
            if decision.action=='reject':proposal.update({'status':'rejected','reviewed_at':db.now()});continue
            if decision.keep_standalone:raise HTTPException(422,'Choose a related Profile experience; standalone details are no longer supported.')
            text=(decision.text or proposal['text']).strip()
            if not text or re.search(PRIVATE,text,re.I):raise HTTPException(400,'Use a nonempty experience or motivation detail; authorization stays in private settings.')
            links=profile_answers.validate_links(c,user,decision.experience_ids) if decision.experience_ids is not None else None
            if proposal['kind']=='motivation' and links:raise HTTPException(400,'Personal motivation stays scoped to its opportunity, not linked to professional experience.')
            if proposal.get('evidence_only') and not decision.save_to_profile:
                if proposal['kind']!='experience':raise HTTPException(400,'Motivation cannot become project evidence.')
                project_id=next((rid for rid in links or [] if profile_answers.owned_experience(c,user,rid)['data']['category']=='project'),'')
                if links is not None and not project_id and not decision.keep_standalone:raise HTTPException(400,'Link the Profile project this answer describes.')
                if decision.keep_standalone and links:raise HTTPException(400,'Standalone stories cannot also have linked experiences.')
                target=project_context.destination(c,user,proposal,project_id or decision.evidence_experience_id,decision.evidence_expected_updated_at,decision.keep_standalone)
                proposal['applied_record_id']=target['id'] if target else ''
            elif decision.save_to_profile:
                if proposal['kind']!='experience':raise HTTPException(400,'Personal motivation stays with the letter, not Profile.')
                rid=decision.profile_record_id
                existing=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='experience'",(rid,user)).fetchone()) if rid else None
                if rid and (not existing or profile_stamps.get(rid,existing['updated_at'])!=decision.profile_expected_updated_at):raise HTTPException(409,'The selected Profile record changed. Reload and review the current record; nothing was overwritten.')
                if existing:profile_stamps.setdefault(rid,existing['updated_at'])
                if existing and (not existing['data'].get('confirmed') or existing['data']['category'] not in ('education','employment','project','volunteering')):raise HTTPException(400,'Choose a confirmed role, project, education or volunteering record.')
                value=copy.deepcopy(existing['data']) if existing else ExperienceItem(title=decision.profile_title or proposal['title'],category=decision.profile_category).model_dump()
                field='contribution' if value['category'] in ('employment','project','volunteering') else 'description'
                old=value.get(field,'');value[field]=old if text in old else old+'\n'+text if old else text;value['confirmed']=True
                value=ExperienceItem.model_validate(value).model_dump();rid=letters.write(c,user,'experience',value,rid or None)
                proposal['applied_record_id']=rid
                if links is not None and rid not in links:links.append(rid)
            if links is None:
                linked=proposal.get('applied_record_id') or proposal.get('profile_record_id','')
                links=[linked] if linked and proposal['kind']=='experience' else []
            proposal['experience_ids']=links
            if proposal.get('supersedes_id'):
                old=proposals[proposal['supersedes_id']]
                if old['status']!='approved':raise HTTPException(409,'The reviewed context changed before this correction.')
                old['status']='superseded'
            proposal.update({'status':'approved','text':text,'reviewed_at':db.now(),'review_revision':db.uid(),'save_to_profile':decision.save_to_profile})
            profile_answers.reviewed(c,user,id,data,proposal,'cover')
            data['context_dirty']=True
        # All changes, including optional Profile additions, commit together or roll back.
    workspace=letters.mutate(user,id,body.expected_version,change)
    if not body.build:return await sync_preview(user,id,body)
    if any(p['status']=='pending' for p in workspace['data']['context_proposals']):raise HTTPException(409,'Review the remaining pending details before building.')
    next_body=body.model_copy(update={'expected_version':workspace['data']['version']})
    workspace,token=letters.begin(user,id,next_body)
    feedback=copy.deepcopy(workspace['data'].get('pending_context_feedback')) if workspace['data'].get('current_revision_id') else None
    if feedback and not feedback.get('revise_all'):
        superseded={'answer:'+p['supersedes_id'] for p in workspace['data']['context_proposals'] if p['id'] in decisions and p['status']=='approved' and p.get('supersedes_id')}
        current=db.get(user,workspace['data']['current_revision_id'],'cover_revision')
        affected=[i for i,p in enumerate(current['data'].get('evidence',[])) if any(e['source_id'] in superseded for e in p['evidence'])]
        feedback['paragraph_indices']=list(dict.fromkeys((feedback.get('paragraph_indices') or [])+affected))
    if feedback and not feedback.get('revision_instruction'):feedback['revision_instruction']='Use the newly reviewed context to develop the related example or genuine motivation, rather than repeating the resume. Preserve other paragraphs.'
    return await letters.draft(user,workspace,token,next_body,feedback)
