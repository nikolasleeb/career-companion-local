"""Account-owned foreground task stages. Metadata only; never prompts or provider text."""
import json
from contextvars import ContextVar
from . import db

_context=ContextVar('task_progress',default=None)
KINDS={'knowledge_coach','personalized_jobs','chat_image','interview_practice','career_coach','job_ai_discovery','job_ai_match','posting_import','resume_guided','cover_letter','analysis','project_analysis','resume','resume_fit','resume_optimize','preparation','interview','assessment','discovery','story_prompts'}
LABELS={'knowledge_coach':'Career Coach reply','personalized_jobs':'personalized job discovery','chat_image':'illustration generation','interview_practice':'interview practice','career_coach':'Career Coach','job_ai_discovery':'AI job discovery','job_ai_match':'Profile fit review','posting_import':'job posting import','cover_letter':'cover-letter action','analysis':'Profile comparison','project_analysis':'project analysis','resume':'resume action','resume_fit':'resume fitting','resume_optimize':'resume optimization','preparation':'practice preparation','interview':'interview review','assessment':'assessment scoring','discovery':'job search','story_prompts':'story prompts'}
STAGES={
    'coach_research':('Checking current career resources','provider'),
    'coach_retrieval':('Retrieving relevant guidance and evidence','local'),
    'coach_generation':('Preparing your sourced coaching response','provider'),
    'coach_validation':('Checking sources and saving the response','local'),
    'searching_jobs':('Searching selected job sources','local'),
    'checking_jobs':('Checking locations, dates and preferences','local'),
    'reading_posting':('Reading job posting','provider'),
    'comparing_profile':('Comparing with your Profile','provider'),
    'saving_comparison':('Saving results','local'),
    'starting':('Preparing resume action','local'),
    'provider':('Waiting for AI response','provider'),
    'processing':('Processing the returned response','local'),
    'questions':('Preparing cover-letter questions','provider'),
    'preparing':('Preparing confirmed experience','local'),
    'comparison':('Refreshing comparison with approved details','provider'),
    'drafting':('Writing the tailored draft','provider'),
    'fitting':('Fitting content to one page','local'),
    'rendering':('Rendering and inspecting the PDF','local'),
    'layout':('Refining wording to correct the layout','provider'),
    'checking':('Checking claims against your saved experience','provider'),
    'reviewing':('Reviewing your answers and requested changes','provider'),
    'saving':('Saving the completed draft preview','local'),
}

def bind(user,task_id,kind='resume_guided'):return _context.set((user,task_id,kind))
def reset(token):_context.reset(token)

def stage(code):
    context=_context.get()
    if not context:return
    label,kind=STAGES[code];user,task_id,process=context
    if code=='starting' and process!='resume_guided':label='Preparing '+LABELS.get(process,'action')
    if process=='interview_practice':label={'drafting':'Preparing an original interview question','reviewing':'Reviewing your interview practice','coach_research':'Checking official company interview resources','saving':'Saving interview practice'}.get(code,label)
    if process=='cover_letter':
        label={'drafting':'Writing the cover-letter draft','reviewing':'Reviewing cover-letter answers and changes','rendering':'Rendering the cover-letter PDF','checking':'Checking cover-letter claims against saved evidence','saving':'Saving the cover-letter result','preparing':'Preparing saved resume and reviewed details'}.get(code,label)
    with db.connect() as c:
        row=c.execute("SELECT result,created_at FROM tasks WHERE id=? AND user_id=? AND status='running'",(task_id,user)).fetchone()
        if not row:return
        payload=json.loads(row['result'] or '{}');previous=payload.get('_task_progress') or {}
        if previous.get('code')==code:return
        stamp=db.now();history=list(previous.get('history',[]))
        if previous.get('code'):
            history.append({k:previous[k] for k in ('code','label','kind','stage_started_at')})
            history[-1]['finished_at']=stamp
        payload['_task_progress']={'code':code,'label':label,'kind':kind,'started_at':row['created_at'],'stage_started_at':stamp,'history':history[-30:]}
        c.execute("UPDATE tasks SET result=?,updated_at=? WHERE id=? AND user_id=? AND status='running'",(json.dumps(payload),stamp,task_id,user))

def finish_payload(payload,status,stamp):
    """Freeze elapsed time on terminal status, in the task's existing transaction."""
    progress=payload.get('_task_progress')
    if progress:progress={**progress,'finished_at':stamp,'status':status}
    return progress

def provider_wait():
    context=_context.get()
    if not context or context[2]=='resume_guided':return
    with db.connect() as c:
        row=c.execute("SELECT result FROM tasks WHERE id=? AND user_id=?",(context[1],context[0])).fetchone()
    progress=json.loads(row['result'] or '{}').get('_task_progress',{}) if row else {}
    if progress.get('kind')!='provider':stage('provider')

def provider_done():
    context=_context.get()
    if context and context[2]!='resume_guided':
        with db.connect() as c:
            row=c.execute('SELECT result FROM tasks WHERE id=? AND user_id=?',(context[1],context[0])).fetchone()
        progress=json.loads(row['result'] or '{}').get('_task_progress',{}) if row else {}
        if progress.get('code') not in ('reading_posting','comparing_profile'):stage('processing')
