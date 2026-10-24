from . import task_progress
"""Cover letters grounded in an exact, immutable saved employer resume."""
import asyncio
import base64
import copy
import io
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from defusedxml import ElementTree
from datetime import date
from fastapi import HTTPException
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from pypdf import PdfReader
from . import ai,ai_settings,db,documents,resume_data,applications,guidance,profile_answers
from .resume_conversation import require,write,public
from .models import CoverContent,CoverLetterOutput,CoverChatOutput,DraftAudit
from .network import ServiceError


INSTRUCTIONS=ai.INSTRUCTIONS.replace('Ask useful questions about qualification evidence and job duties, never availability questions. Direct eligibility and authorization answers to private Profile settings.','For cover letters, ask useful questions about genuine motivation, relevant stories, individual decisions, audience and outcomes. Do not ask eligibility, authorization or availability questions. Reviewed answer sources are applicant evidence; unreviewed chat may only produce proposals for human review.')

def source_resume(user,job_id,resume_id):
    job=require(user,job_id,'job');resume=require(user,resume_id,'resume');data=resume['data']
    linked=data.get('job_id')
    if not linked and data.get('analysis_id'):
        analysis=require(user,data['analysis_id'],'analysis');linked=analysis['data'].get('job_id')
    if linked!=job_id:raise HTTPException(409,'Choose a resume saved for this posting.')
    snapshot={'name':data.get('name',''),'headline':data.get('headline',''),'contact_lines':data.get('contact_lines',str(data.get('contact','')).splitlines()),'sections':[]}
    for section in data['sections']:
        snapshot['sections'].append({'title':section['title'],'entries':[{k:copy.deepcopy(entry.get(k,'' if k!='bullets' else [])) for k in ('title','organization','dates','location','details','category','bullets')} for entry in section['entries']]})
    if not any(s['entries'] for s in snapshot['sections']):raise HTTPException(409,'Choose a resume containing reviewed experience or education.')
    return resume,snapshot,copy.deepcopy(data.get('posting_snapshot') or job['data'])


def title(snapshot,posting):
    return resume_data.resume_title(posting,name=snapshot.get('name','')).removesuffix('-Resume')+'-Cover-Letter'


def sources(data):
    """Only employer-visible selected resume content. Never full Profile entry fields."""
    rows=[];snapshot=data['resume_snapshot']
    if snapshot.get('headline'):rows.append({'id':'resume:headline','label':'Resume headline','text':snapshot['headline']})
    for si,section in enumerate(snapshot['sections']):
        for ei,entry in enumerate(section['entries']):
            heading=' | '.join(str(entry.get(k) or '') for k in ('title','organization','dates','details') if entry.get(k))
            rows.append({'id':f'resume:{si}:{ei}:heading','label':entry['title'],'text':heading})
            for bi,bullet in enumerate(entry['bullets']):
                if bullet.strip():rows.append({'id':f'resume:{si}:{ei}:{bi}','label':entry['title'],'text':bullet,'context':heading})
    for p in data.get('effective_context',data.get('context_proposals',[])):
        if p['status']=='approved':rows.append({'id':'answer:'+p['id'],'label':p['title']+' · reviewed answer','text':p['text'],'kind':p['kind'],'source_message_id':p['source_message_id'],'review_revision':p['review_revision']})
    for a in data.get('library_sources',[]):
        rows.append({'id':'library:'+a['id'],'label':a['title']+' · reviewed Profile answer','text':a['text'],'version':a['version'],'experience_ids':a.get('experience_ids',[]),'association_note':'One shared fact; linked records indicate context, not separate accomplishments.'})
    return rows


def effective_context(user,data):
    effective=[];active_answers={r['id'] for r in profile_answers.confirmed(user)}
    for p in data.get('context_proposals',[]):
        value=copy.deepcopy(p);answer=db.get(user,p.get('profile_answer_id',''),'profile_answer') if p.get('profile_answer_id') else None
        if answer:
            if answer['id'] not in active_answers:continue
            value['text']=answer['data']['text'];value['library_version']=answer['data']['version']
        effective.append(value)
    return effective


def mutate(user,id,version,change):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        record=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='cover_workspace'",(id,user)).fetchone())
        if not record:raise HTTPException(404,'Cover letter workspace not found.')
        data=record['data']
        if data['version']!=version:raise HTTPException(409,'This letter changed in another window. Reload before retrying; the previous draft is preserved.')
        change(data,c);data['version']+=1;write(c,user,'cover_workspace',data,id)
    return require(user,id,'cover_workspace')


def start(user,body):
    resume,snapshot,posting=source_resume(user,body.job_id,body.resume_id)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='cover_workspace'",(user,)) if json.loads(r['payload'])['resume_id']==body.resume_id),None)
        if existing:id=existing['id']
        else:
            data={'job_id':body.job_id,'resume_id':body.resume_id,'resume_saved_at':resume['created_at'],'resume_title':applications.public(resume)['data']['title'],'resume_snapshot':snapshot,'posting_snapshot':posting,'version':0,'content':CoverContent(letter_date=body.letter_date,subject='Application for '+posting.get('title','the position')).model_dump(),'instructions':'','messages':[],'revision_ids':[],'current_revision_id':None,'request_token':None}
            id=write(c,user,'cover_workspace',data)
    return state(user,id)


def state(user,id):
    record=require(user,id,'cover_workspace');data=record['data'];data['effective_context']=effective_context(user,data);data.setdefault('messages',[]);data.setdefault('questions',[]);data.setdefault('context_proposals',[]);data.setdefault('context_dirty',False);profile_answers.stable_questions(data,'cover');data['content']=CoverContent.model_validate(data['content']).model_dump();result=public(record)
    result['current']=public(require(user,data['current_revision_id'],'cover_revision')) if data.get('current_revision_id') else None
    result['history']=[{'id':r['id'],'created_at':r['created_at'],'summary':r['data']['summary']} for rid in data['revision_ids'] if (r:=db.get(user,rid,'cover_revision'))]
    result['saved_versions']=[public(r) for r in db.list_entities(user,'cover_letter') if r['data'].get('resume_id')==data['resume_id']]
    result['sources']=sources(data)
    result['current_sources']=sources({**data,'effective_context':(result['current'] or {}).get('data',{}).get('approved_context',[]),'context_proposals':(result['current'] or {}).get('data',{}).get('approved_context',[]),'library_sources':(result['current'] or {}).get('data',{}).get('library_sources',[])})
    result['preview_stale']=bool(result['current'] and result['current']['data']['request_token']!=data['request_token'])
    with db.connect() as c:tasks=c.execute("SELECT id,status,error,result,updated_at FROM tasks WHERE user_id=? AND kind='cover_letter' ORDER BY created_at DESC LIMIT 30",(user,)).fetchall()
    own=[r for r in tasks if id in (r['result'] or '')]
    result['pending_task']=next((r['id'] for r in own if r['status'] in ('queued','running')),None)
    result['last_failure']=own[0]['error'] if own and own[0]['status'] in ('failed','interrupted') and own[0]['updated_at']>record['updated_at'] else None
    return result


def begin(user,id,body,preserve_preview=False):
    token=body.request_token or db.uid()
    def change(data,c):
        data['effective_context']=effective_context(user,data)
        data['library_sources']=[{'id':r['id'],'experience_ids':profile_answers.experience_ids(r['data']),**{k:copy.deepcopy(r['data'][k]) for k in ('title','text','version','answer_kind','sources')}} for r in profile_answers.reusable(user,data['job_id'],data.get('selected_answer_ids',[]))]
        data.update({'request_token':token,'content':body.content.model_dump(),'instructions':body.instructions})
        if preserve_preview and data.get('current_revision_id'):
            current=db.get(user,data['current_revision_id'],'cover_revision')
            if current and CoverContent.model_validate(current['data']['content'])==body.content:data['request_token']=current['data']['request_token']
        messages=data.setdefault('messages',[])
        if getattr(body,'text',None) and not any(m.get('request_token')==token and m['role']=='user' for m in messages):
            messages.append({'id':db.uid(),'role':'user','text':body.text,'request_token':token,'created_at':db.now()})
    record=mutate(user,id,body.expected_version,change)
    return record,token


def contact_lines(snapshot,content):
    lines=snapshot.get('contact_lines',[])
    if content.get('header_style','compact')=='full':return lines
    # Keep the resume's actual email/phone/location, with long portfolio URLs optional.
    result=[]
    for line in lines:
        parts=[p.strip() for p in line.split('|')]
        parts=[p for p in parts if p and not re.search(r'https?://|www\.|(?:github|linkedin)\.com',p,re.I)]
        if parts:result.append(' | '.join(parts))
    return result


def plain(snapshot,posting,content):
    lines=[snapshot.get('name',''),*contact_lines(snapshot,content),'']
    metadata=[]
    if content['letter_date']:metadata.append(date.fromisoformat(content['letter_date']).strftime('%B %d, %Y').replace(' 0',' '))
    if posting.get('company'):metadata.append(posting['company'])
    if metadata:lines.extend([' · '.join(metadata),''])
    if content.get('show_subject') and content.get('subject'):lines.extend([content['subject'],''])
    lines.extend([content['greeting'],'',*sum(([p.strip(),''] for p in content['paragraphs'] if p.strip()),[]),content['closing'],snapshot.get('name','')])
    return '\n'.join(str(v) for v in lines).strip()+'\n'


def measure(pdf):
    executable=shutil.which('pdftotext')
    if not executable:return None
    with tempfile.TemporaryDirectory(prefix='nextstep-letter-layout-') as folder:
        path=Path(folder)/'letter.pdf';path.write_bytes(pdf)
        try:
            value=subprocess.run([executable,'-bbox',str(path),'-'],capture_output=True,check=True,timeout=30)
            page=ElementTree.fromstring(value.stdout).find('.//{*}page');words=page.findall('.//{*}word')
            if not words:return 0
            return round((max(float(w.get('yMax')) for w in words)-min(float(w.get('yMin')) for w in words))/float(page.get('height')),4)
        except (OSError,subprocess.SubprocessError,ElementTree.ParseError,ValueError,AttributeError):
            raise ServiceError('The letter PDF could not be inspected. Your previous preview is preserved.') from None


def render_document(snapshot,posting,content):
    if not any(p.strip() for p in content['paragraphs']):raise ServiceError('Write a paragraph or create an AI draft before previewing. Your inputs are preserved.')
    # Bounded local typography adjustments; never change text or stretch short letters with blank space.
    for body_size,spacing,after in ((12,1.18,12),(11.5,1.14,10),(11,1.10,8)):
        doc=Document();section=doc.sections[0]
        section.page_width=Inches(8.5);section.page_height=Inches(11)
        section.top_margin=section.bottom_margin=Inches(.7);section.left_margin=section.right_margin=Inches(.8)
        normal=doc.styles['Normal'];normal.font.name='Arial';normal.font.size=Pt(body_size);normal.font.color.rgb=RGBColor(0,0,0)
        normal.paragraph_format.space_after=Pt(after);normal.paragraph_format.line_spacing=spacing
        if snapshot.get('name'):
            p=doc.add_paragraph();run=p.add_run(snapshot['name']);run.bold=True;run.font.size=Pt(18);p.paragraph_format.space_after=Pt(4);p.paragraph_format.keep_with_next=True
        for line in contact_lines(snapshot,content):
            if line.strip():
                p=doc.add_paragraph(line);p.paragraph_format.space_after=Pt(3);p.paragraph_format.keep_with_next=True
                for run in p.runs:run.font.size=Pt(10.5)
        metadata=[]
        if content['letter_date']:metadata.append(date.fromisoformat(content['letter_date']).strftime('%B %d, %Y').replace(' 0',' '))
        if posting.get('company'):metadata.append(posting['company'])
        if metadata:doc.add_paragraph(' · '.join(metadata))
        if content.get('show_subject') and content.get('subject'):
            p=doc.add_paragraph();p.add_run(content['subject']).bold=True;p.paragraph_format.keep_with_next=True
        p=doc.add_paragraph(content['greeting']);p.paragraph_format.keep_with_next=True
        for text in content['paragraphs']:
            if text.strip():
                p=doc.add_paragraph(text.strip());p.paragraph_format.widow_control=True;p.paragraph_format.keep_together=True
        p=doc.add_paragraph(content['closing']);p.paragraph_format.keep_with_next=True;p.paragraph_format.space_after=Pt(3)
        if snapshot.get('name'):doc.add_paragraph(snapshot['name'])
        doc.core_properties.author='';doc.core_properties.title='Cover Letter'
        buffer=io.BytesIO();doc.save(buffer);word=buffer.getvalue();pdf=documents.docx_pdf(word)
        pages=len(PdfReader(io.BytesIO(pdf)).pages)
        if pages==1:break
    fill=measure(pdf);short=pages==1 and fill is not None and fill<2/3
    message=(f'This letter fills {pages} pages. Shorten it before saving; all pages are shown.' if pages>1 else 'Below the two-thirds-page target. Ask the chat to develop another supported example, or keep a concise letter if the saved resume has no useful detail to add.' if short else '')
    return {'pages':pages,'validated':pages==1,'body_font_pt':body_size,'word_count':len(re.findall(r'\S+',' '.join(content['paragraphs']))),'page_fill':fill,'target_fill':2/3,'below_target':short,'message':message,'format_version':2},{'docx':base64.b64encode(word).decode(),'pdf':base64.b64encode(pdf).decode()}


def commit_revision(user,workspace,token,content,layout,artifacts,evidence,summary,usage=None,messages=None,approved_context=None,writing_guidance=None):
    id=workspace['id'];data=workspace['data'];revision_id=db.uid()
    parent=db.get(user,data['current_revision_id'],'cover_revision') if data.get('current_revision_id') else None
    context_used=approved_context if approved_context is not None else (parent or {}).get('data',{}).get('approved_context',[])
    def change(current,c):
        if current['request_token']!=token:raise HTTPException(409,'A newer letter preview superseded this result.')
        value={'project_snapshot_ids':list(data.get('project_snapshot_ids',[])),'workspace_id':id,'job_id':data['job_id'],'resume_id':data['resume_id'],'resume_snapshot':data['resume_snapshot'],'posting_snapshot':data['posting_snapshot'],'title':title(data['resume_snapshot'],data['posting_snapshot']),'content':content,'layout':layout,'artifacts':artifacts,'evidence':evidence,'summary':summary,'usage':usage,'request_token':token,'approved_context':context_used,'writing_guidance':writing_guidance,'library_sources':copy.deepcopy((parent or {}).get('data',{}).get('library_sources',[]) if approved_context is None else data.get('library_sources',[]))}
        if approved_context is not None:current['context_dirty']=False;current.pop('pending_context_feedback',None)
        write(c,user,'cover_revision',value,revision_id)
        current.setdefault('messages',[]).extend(messages or [])
        current.update({'current_revision_id':revision_id,'content':content,'revision_ids':current['revision_ids']+[revision_id]})
    mutate(user,id,data['version'],change)
    return state(user,id)


async def render(user,id,body):
    workspace,token=begin(user,id,body);data=workspace['data'];content=body.content.model_dump()
    task_progress.stage('rendering')
    layout,artifacts=await asyncio.to_thread(render_document,data['resume_snapshot'],data['posting_snapshot'],content)
    current=db.get(user,data.get('current_revision_id',''),'cover_revision') if data.get('current_revision_id') else None
    # Retain a source link only when its paragraph remains exactly the approved AI text.
    previous=(current or {}).get('data',{}).get('evidence',[])
    evidence=[row for row in previous if row['text'] in content['paragraphs']]
    task_progress.stage('saving')
    result=commit_revision(user,workspace,token,content,layout,artifacts,evidence,'Updated the letter preview locally. No AI request.',(current or {}).get('data',{}).get('usage'),approved_context=None,writing_guidance=(current or {}).get('data',{}).get('writing_guidance'))
    return result


def validate_output(output,rows,posting):
    allowed={r['id']:r['text'] for r in rows};allowed['posting']='\n'.join(v for v in posting.values() if isinstance(v,str))
    for p in output['paragraphs']:
        if not p['evidence']:raise ServiceError('A cover-letter paragraph was missing its supporting source.')
        for source in p['evidence']:
            if source['source_id'] not in allowed or not ai.valid_quote(source['quote'],allowed[source['source_id']]):raise ServiceError('A letter source did not match the saved resume, reviewed answer or posting. Your previous draft remains intact.')
        if ai.numeric_facts(p['text'])-ai.numeric_facts(' '.join(e['quote'] for e in p['evidence'])):raise ServiceError('The letter introduced a number missing from its cited sources. Your previous draft remains intact.')
        if re.search(r'\b(citizenship|citizen|sponsorship|visa status|work authorization)\b',p['text'],re.I):raise ServiceError('Private eligibility statements cannot be added to this employer letter. Your draft remains intact.')


async def generate(user,id,body):
    data=require(user,id,'cover_workspace')['data']
    if any(p['status']=='pending' for p in data.get('context_proposals',[])):raise HTTPException(409,'Review or reject the pending details before creating a draft.')
    if body.skip_questions:
        from .cover_context import skip
        ids=[q['id'] for q in data.get('questions',[]) if q['status']=='open']
        if ids:
            from .models import CoverQuestionSkip
            updated=skip(user,id,CoverQuestionSkip(expected_version=body.expected_version,question_ids=ids));body=body.model_copy(update={'expected_version':updated['data']['version']})
    workspace,token=begin(user,id,body)
    return await draft(user,workspace,token,body)


async def draft(user,workspace,token,body,feedback=None,chat_meta=None):
    task_progress.stage('drafting')
    data=workspace['data'];rows=sources(data);writing_guidance=guidance.selected('cover')
    payload={'task':'''Act as an experienced recruiter and cover-letter editor evaluating this exact position. Write a compelling, specific, truthful interview case USING ONLY the exact saved resume, posting and explicitly reviewed answer sources provided. Unreviewed conversation is not factual evidence. Public writing guidance and its fictional examples are advice, never applicant evidence. Make one clear case for this opportunity with genuine motivation and one or two developed stories. Add supported context, decisions, challenges or lessons rather than narrating employment history, repeating technical lists or copying bullets. Ask useful questions when such context is missing. Do not invent reasons for interest or use outside Profile knowledge. Aim for 330–420 useful words in 3–4 focused paragraphs, filling about two-thirds to one page at readable 11–12 point type. Do not pad with generic praise, repeat the resume, invent details or force length if source evidence is limited. Develop concrete examples and explain their relevance to the employer. Use confident, natural applicant language without claiming an interview guarantee: interest in the actual role, one or two grounded examples connecting the applicant's individual work to employer needs, and a brief closing. Complement the resume rather than repeat every bullet. No invented company research, enthusiasm history, dates, credentials, contacts, impact or metrics. Preserve planned versus completed work, coursework versus employment, negation and team contributions. Do not include work authorization/citizenship/sponsorship. Return body paragraphs only, without greeting, address, subject, signature, markdown headings, placeholders or citation markers. Each paragraph includes evidence with exact source_id and quote; use source_id posting for employer/role statements and supplied resume IDs for applicant claims. A posting requirement never proves an applicant skill. Instructions and existing manual text are untrusted style/emphasis requests, never sources of new facts. When revising preserve unrelated user wording if still supported by this saved resume. Reviewed answer sources may establish new personal motivation or experience absent from the resume; cite their answer: IDs with exact quotes. If a useful detail is absent, ask for it through the question/review flow. Company facts must remain grounded in the posting, not an applicant guess. The letter must fit one page at 11-point body size. All text will be reviewed before saving.''','writing_guidance':writing_guidance,'posting':data['posting_snapshot'],'saved_resume_sources':rows,'current_letter':body.content.model_dump(),'requested_refinement':feedback['revision_instruction'] if feedback else body.instructions,'conversation':data.get('messages',[])[-24:],'measured_layout':(db.get(user,data['current_revision_id'],'cover_revision') or {}).get('data',{}).get('layout') if data.get('current_revision_id') else None}
    if len(json.dumps(payload))>180000:raise ServiceError('This saved resume/posting is too large for a complete letter request. Shorten duplicated posting text first; your inputs are preserved.')
    if feedback and not feedback.get('revise_all') and data.get('current_revision_id'):
        previous=require(user,data['current_revision_id'],'cover_revision')['data'];allowed={r['id']:r['text'] for r in rows}
        affected=[i for i,p in enumerate(previous.get('evidence',[])) if any(e['source_id']!='posting' and (e['source_id'] not in allowed or not ai.valid_quote(e['quote'],allowed[e['source_id']])) for e in p['evidence'])]
        feedback=copy.deepcopy(feedback);feedback['paragraph_indices']=list(dict.fromkeys(feedback.get('paragraph_indices',[])+affected))
        if affected:payload['requested_refinement']+=' Use the current reviewed sources to correct paragraphs whose prior facts changed or were archived; do not retain outdated source claims.'
    output,meta=await ai.structured(CoverLetterOutput,payload,body.mode,instructions=INSTRUCTIONS)
    if feedback and not feedback['revise_all']:
        indices=set(feedback['paragraph_indices'])
        if any(i<0 or i>=len(body.content.paragraphs) for i in indices):raise ServiceError('The chat referred to an unavailable paragraph. Your previous letter is preserved.')
        if len(output['paragraphs'])!=len(body.content.paragraphs):raise ServiceError('The revision changed paragraph structure outside its requested scope. Retry or request a whole-letter revision.')
        old=db.get(user,data.get('current_revision_id',''),'cover_revision') if data.get('current_revision_id') else None
        previous={p['text']:p for p in (old or {}).get('data',{}).get('evidence',[])}
        for i,text in enumerate(body.content.paragraphs):
            if i not in indices:
                if text in previous:output['paragraphs'][i]=previous[text]
                else:output['paragraphs'][i]={'text':text,'evidence':[{'source_id':r['id'],'quote':r['text']} for r in sorted(rows,key=lambda r:-len(set(re.findall(r'[a-z]+',text.lower())) & set(re.findall(r'[a-z]+',r['text'].lower()))))[:12]]}
    validate_output(output,rows,data['posting_snapshot'])
    task_progress.stage('checking')
    audit,audit_meta=await ai.structured(DraftAudit,{'task':'''Check every applicant claim in this cover letter ONLY against the exact saved-resume sources AND reviewed answer sources. Approved personal motivation may come from an answer. Unreviewed chat and writing guidance (including fictional examples) are not evidence. Company claims must be supported by the posting. The job posting establishes employer facts, not applicant qualifications. Reject invented or exaggerated achievements, tools, metrics, degree status, responsibilities, employer research, unsupported references, removed limitations, team work presented as individual work, or future work presented as completed. Check that each paragraph's cited sources support its applicant claims. approved=true only if all claims are grounded. Do not rewrite.''','saved_resume_sources':rows,'posting':data['posting_snapshot'],'letter':output},body.mode,instructions=INSTRUCTIONS)
    if not audit['approved'] or audit['issues']:raise ServiceError('The source check could not approve the letter. '+' '.join(audit['issues'][:3])+' Your previous draft and inputs remain available.')
    content={**body.content.model_dump(),'paragraphs':[p['text'] for p in output['paragraphs']]}
    task_progress.stage('rendering')
    layout,artifacts=await asyncio.to_thread(render_document,data['resume_snapshot'],data['posting_snapshot'],content)
    costs=[m.get('estimated_token_cost_usd') for m in (meta,audit_meta,chat_meta) if m]
    usage={'ai':meta,'audit_ai':audit_meta,'chat_ai':chat_meta,'actual_cost_usd':round(sum(costs),6) if all(c is not None for c in costs) else None}
    summary=re.sub(r'\b[0-9]+[ -]word\b',str(layout['word_count'])+'-word',output['summary'])
    if layout['below_target']:summary+=' The rendered letter remains below the two-thirds-page target; additional supported detail may help.'
    reply=feedback.get('reply','I updated the related paragraphs using your reviewed details.') if feedback else 'I built a source-checked letter from your selected saved resume. Tell me what you would like to change.'
    messages=[{'id':db.uid(),'role':'assistant','text':reply,'created_at':db.now(),'usage':usage}]
    task_progress.stage('saving')
    return commit_revision(user,workspace,token,content,layout,artifacts,output['paragraphs'],summary,usage,messages,approved_context=[copy.deepcopy(p) for p in data.get('effective_context',data.get('context_proposals',[])) if p['status']=='approved'],writing_guidance=writing_guidance)


async def send(user,id,body):
    from .cover_context import send as context_send
    return await context_send(user,id,body)


def estimate(user,id,mode):
    data=require(user,id,'cover_workspace')['data'];option=ai_settings.resolve(db.settings(user),mode)
    count=max(1500,len(json.dumps({'sources':sources(data),'posting':data['posting_snapshot'],'content':data['content'],'instructions':data['instructions'],'messages':data.get('messages',[])[-24:],'writing_guidance':guidance.selected('cover'),'questions':data.get('questions',[]),'context':data.get('context_proposals',[])}))//4)
    first=ai_settings.estimate(option['model'],option['reasoning_effort'],count+1300,1800,service_tier=option['service_tier'])
    second=ai_settings.estimate(option['model'],option['reasoning_effort'],count+3500,500,service_tier=option['service_tier'])
    chat=ai_settings.estimate(option['model'],option['reasoning_effort'],count+1800,700,service_tier=option['service_tier'])
    questions=ai_settings.estimate(option['model'],option['reasoning_effort'],count+1600,1200,service_tier=option['service_tier'])
    return {**option,'questions_usd':questions['usd'],'chat_usd':round(first['usd']+second['usd']+chat['usd'],6) if first['usd'] is not None and second['usd'] is not None and chat['usd'] is not None else None,'usd':round(first['usd']+second['usd'],6) if first['usd'] is not None and second['usd'] is not None else None,'note':'Planning estimate for drafting/refining plus a separate source check. Actual usage and retries vary. Local edits, previews, saving and downloads do not call OpenAI.','pricing_date':first['pricing_date']}


def restore(user,id,body):
    revision=require(user,body.revision_id,'cover_revision')
    if revision['data']['workspace_id']!=id:raise HTTPException(409,'Choose a revision of this letter.')
    def change(data,c):data.update({'current_revision_id':revision['id'],'content':revision['data']['content'],'request_token':revision['data']['request_token']})
    mutate(user,id,body.expected_version,change)
    return state(user,id)


def finalize(user,id,body):
    revision=require(user,body.revision_id,'cover_revision');value=revision['data']
    if value['workspace_id']!=id:raise HTTPException(409,'Choose the reviewed revision of this letter.')
    require(user,value['resume_id'],'resume')
    def change(data,c):
        if data['current_revision_id']!=revision['id'] or data['request_token']!=value['request_token']:raise HTTPException(409,'Review the current letter preview before saving.')
        if not value['layout']['validated'] or value['layout']['pages']!=1:raise HTTPException(409,'Shorten the letter to one page before saving downloads.')
        saved=value.get('finalized_letter_id')
        if not saved:
            saved=write(c,user,'cover_letter',{**copy.deepcopy(value),'revision_id':revision['id']});value['finalized_letter_id']=saved;write(c,user,'cover_revision',value,revision['id'])
        data['last_saved_letter_id']=saved
    result=mutate(user,id,body.expected_version,change)
    saved=require(user,result['data']['last_saved_letter_id'],'cover_letter')
    attach(user,saved);applications.select_saved_letter(user,saved)
    return state(user,id)


def attach(user,letter):
    data=letter['data'];resume=require(user,data['resume_id'],'resume')
    applications.attach_resume(user,resume)
    with applications.LOCK:
        record=next((r for r in db.list_entities(user,'application') if r['data'].get('job_id')==data['job_id']),None)
        if not record:return
        updated=copy.deepcopy(record['data']);attachments=updated.setdefault('attachments',[])
        if not any(a['record_id']==letter['id'] for a in attachments):attachments.append({'kind':'cover_letter','record_id':letter['id']})
        db.save(user,'application',updated,record['id'])


def export_data(data,format):
    if format in ('pdf','docx'):
        return base64.b64decode(data['artifacts'][format]),{'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}[format]
    if format=='txt':return plain(data['resume_snapshot'],data['posting_snapshot'],data['content']).encode(),'text/plain; charset=utf-8'
    raise HTTPException(400,'Choose PDF, Word or TXT.')


def filename(data,format):
    base=re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]','-',data['title']).strip(' .')
    return base.encode()[:190].decode('utf-8','ignore')+'.'+format
