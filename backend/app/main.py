import asyncio
import base64
import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse, quote
from fastapi import FastAPI, Request, Response, Depends, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from . import config, db, auth, ai, documents, integrations, resume_data, resume_parser, transcript_parser, credentials, ai_settings, applications, resume_builder, job_parser, optimization, resume_conversation, cover_letters, guidance, cover_context, profile_answers, question_answers, onboarding, certifications, cost_history, updates
from .models import *
from .network import ServiceError, public_fetch, html_job
from . import task_progress, posting_extraction

workers={}

@asynccontextmanager
async def lifespan(app):
    db.init()
    onboarding.migrate()
    yield
    tasks=list(workers.values())
    for task in tasks: task.cancel()
    if tasks: await asyncio.gather(*tasks,return_exceptions=True)

def workflow_access(request:Request):
    if onboarding.restricted(request.url.path):
        user=auth.current(request)
        onboarding.require_complete(user['id'])

app=FastAPI(dependencies=[Depends(workflow_access)],title='Career Companion',version=updates.installed()['version'],lifespan=lifespan)
from .local_access import LocalAccess
app.add_middleware(LocalAccess)
from .security import ResourceBoundary
app.add_middleware(ResourceBoundary)
from . import private_answers, private_profile, application_agent, assistant_ai
app.include_router(private_answers.router)
app.include_router(private_profile.router)
app.include_router(application_agent.router)
from . import application_documents
app.include_router(application_documents.router)

@app.middleware('http')
async def boundaries(request, call_next):
    length=request.headers.get('content-length','0')
    maximum=11*1024*1024 if re.fullmatch(r'/api/applications/[^/]+/documents',request.url.path) else 51*1024*1024 if request.url.path in ('/api/jobs/import-document','/api/jobs/from-document','/api/analyses/from-document') else 52*1024*1024 if request.url.path=='/api/account/import' else 33*1024*1024 if request.url.path=='/api/project-sources/upload' else 11*1024*1024 if request.url.path in ('/api/documents','/api/transcripts/parse','/api/certificates') else 1024*1024
    try:
        if int(length)<0:return JSONResponse({'detail':'Invalid request size.'},400)
        if int(length)>maximum: return JSONResponse({'detail':'This request exceeds the size limit.'},413)
    except ValueError: return JSONResponse({'detail':'Invalid request size.'},400)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        expected=request.url.scheme+'://'+request.headers.get('host','')
        if origin and origin!=expected: return JSONResponse({'detail':'Cross-origin changes are not allowed.'},403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='SAMEORIGIN' if request.url.path.endswith('/preview') else 'DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.endswith('/preview'):
        response.headers['Content-Security-Policy']=response.headers['Content-Security-Policy'].replace("frame-ancestors 'none'","frame-ancestors 'self'")
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(ServiceError)
async def service_error(request,error): return JSONResponse({'detail':str(error)},400)

@app.exception_handler(RequestValidationError)
async def invalid_request(request,error):
    return JSONResponse({'detail':'; '.join('.'.join(str(x) for x in e['loc'][1:])+': '+e['msg'] for e in error.errors())},422)

def require(user,entity_id,kind):
    result=db.get(user,entity_id,kind)
    if not result: raise HTTPException(404,'Record not found.')
    return result

def capabilities_for(user):
    own=bool(credentials.get(user))
    return {**config.capabilities(),'openai':bool(own or (config.OPENAI_KEY if config.ALLOW_SERVER_AI_KEY else '')),
            'web_search':bool(credentials.effective(user) and config.ENABLE_WEB_SEARCH),
            'openai_key_source':'account' if own else 'installation' if config.OPENAI_KEY and config.ALLOW_SERVER_AI_KEY else 'none',
            'ai':ai_settings.public(db.settings(user))}

def require_ai(user):
    if not credentials.effective(user): raise HTTPException(503,'Add your OpenAI API key in Settings to enable AI. Manual records and exports remain available.')

def finish_task(task_id,user,status,*,result=None,saved_inputs=None,error=None):
    stamp=db.now()
    with db.connect() as c:
        row=c.execute('SELECT result FROM tasks WHERE id=? AND user_id=?',(task_id,user)).fetchone()
        if not row:return
        payload=json.loads(row['result'] or '{}')
        progress=task_progress.finish_payload(payload,status,stamp)
        if status=='completed':
            payload={'_task_inputs':saved_inputs,'_task_result':result} if saved_inputs else result
            if progress:payload={'_task_result':result,'_task_progress':progress,**({'_task_inputs':saved_inputs} if saved_inputs else {})}
        elif progress:payload['_task_progress']=progress
        c.execute('UPDATE tasks SET status=?,result=?,error=?,updated_at=? WHERE id=? AND user_id=?',(status,json.dumps(payload),error,stamp,task_id,user))

async def run_task(task_id,user,work):
    with db.connect() as c: c.execute("UPDATE tasks SET status='running',updated_at=? WHERE id=?",(db.now(),task_id))
    with db.connect() as c:
        row=c.execute('SELECT kind,result FROM tasks WHERE id=?',(task_id,)).fetchone()
        saved_inputs=(json.loads(row['result']).get('inputs') if row and row['result'] and row['kind'] in ('analysis','posting_import','project_analysis','story_prompts') else None)
        task_inputs=(json.loads(row['result']).get('inputs') or {}) if row and row['result'] else {}
    context_token=ai.set_user_context(user,task_id=task_id,process=row['kind'] if row else 'other',operation=str(task_inputs.get('operation',''))[:80])
    progress_token=task_progress.bind(user,task_id,row['kind']) if row and row['kind'] in task_progress.KINDS else None
    try:
        if progress_token is not None:task_progress.stage('starting')
        result=await asyncio.wait_for(work(),timeout=1200 if row and row['kind']=='analysis' else 600)
        finish_task(task_id,user,'completed',result=result,saved_inputs=saved_inputs)
    except asyncio.TimeoutError:
        limit='twenty' if row and row['kind']=='analysis' else 'ten'
        finish_task(task_id,user,'failed',error='This action reached the '+limit+'-minute limit. Saved inputs remain available for retry.')
    except asyncio.CancelledError:
        finish_task(task_id,user,'interrupted',error='The operation was interrupted. Saved inputs remain available for retry.')
        raise
    except Exception as error:
        message=str(error) if isinstance(error,ServiceError) else str(error.detail) if isinstance(error,HTTPException) else 'The operation could not finish safely. Saved inputs remain available; retry or check the integration configuration.'
        finish_task(task_id,user,'failed',error=message)
    finally:
        if progress_token is not None:task_progress.reset(progress_token)
        ai.reset_user_context(context_token)
        workers.pop(task_id,None)

def start_task(user,kind,work,inputs=None):
    task_id=db.uid();stamp=db.now()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        # A lost task-start response can be checked with the same token, without
        # initiating a second provider request. Tokens are scoped to this account.
        if kind in ('analysis','posting_import','project_analysis','story_prompts') and inputs and inputs.get('request_token'):
            for previous in c.execute("SELECT id,status,result FROM tasks WHERE user_id=? AND kind=? ORDER BY created_at DESC",(user,kind)):
                saved=json.loads(previous['result']) if previous['result'] else {}
                original=saved.get('_task_inputs',saved.get('inputs',{})) if isinstance(saved,dict) else {}
                if original.get('request_token')==inputs['request_token']:
                    if original!=inputs:raise HTTPException(409,'This request belongs to different inputs. Check its original result first.')
                    return {'task_id':previous['id'],'status':previous['status']}
        if kind=='project_analysis' and inputs:
            for previous in c.execute("SELECT id,status,result FROM tasks WHERE user_id=? AND kind=? AND status IN ('queued','running')",(user,kind)):
                saved=json.loads(previous['result']) if previous['result'] else {}
                if saved.get('inputs',{}).get('snapshot_id')==inputs.get('snapshot_id'):
                    return {'task_id':previous['id'],'status':previous['status']}
        running=c.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND status IN ('queued','running')",(user,)).fetchone()[0]
        discovery=c.execute("SELECT 1 FROM tasks WHERE user_id=? AND kind='discovery' AND status IN ('queued','running')",(user,)).fetchone()
        total=c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')").fetchone()[0]
        if total>=config.GLOBAL_TASK_LIMIT:raise HTTPException(503,'The server is busy. Wait for a running task to finish.')
        if running>=2 or (kind=='discovery' and discovery): raise HTTPException(409,'An operation is already running. Wait for it to finish before starting another.')
        c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(task_id,user,kind,'queued',json.dumps({'inputs':inputs}) if inputs else None,None,stamp,stamp))
    workers[task_id]=asyncio.create_task(run_task(task_id,user,work))
    return {'task_id':task_id,'status':'queued'}

@app.get('/api/health')
def health(): return {'status':'ok',**updates.installed()}

@app.get('/api/updates')
def update_status(user=Depends(auth.current)):
    return updates.status()

@app.post('/api/updates/check')
def check_updates(body:updates.Check,user=Depends(auth.current)):
    return updates.check(force=body.force)

@app.post('/api/auth/register')
def register(body:Credentials,request:Request,response:Response):
    auth.throttle(('register',request.client.host if request.client else 'local'))
    user=db.uid()
    try:
        password=auth.hasher.hash(body.password)
        with db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT INTO users VALUES(?,?,?,?,?)',(user,body.username.lower(),password,json.dumps({'mode':'economy','name':'','contact':''}),db.now()))
    except sqlite3.IntegrityError: raise HTTPException(409,'That username is already in use.') from None
    for board in [{'provider':'greenhouse','board':'figma','company':'Figma'},{'provider':'ashby','board':'notion','company':'Notion'}]: db.save(user,'board',board)
    csrf=auth.issue(response,user)
    return {'id':user,'username':body.username.lower(),'csrf':csrf,'settings':db.settings(user),'capabilities':capabilities_for(user),'onboarding':onboarding.status(user)}

@app.post('/api/auth/login')
def login(body:Credentials,request:Request,response:Response):
    auth.throttle(('login',body.username.lower(),request.client.host if request.client else 'local'))
    with db.connect() as c: row=c.execute('SELECT * FROM users WHERE username=?',(body.username.lower(),)).fetchone()
    if not row or not auth.verify(row['password'],body.password): raise HTTPException(401,'Username or password is incorrect.')
    with db.connect() as c:
        previous=c.execute('SELECT user_id,csrf FROM sessions WHERE token_hash=?',(auth.digest(request.cookies.get('next_step_session','')),)).fetchone()
    if previous:application_agent.revoke_session(previous['user_id'],previous['csrf'])
    csrf=auth.issue(response,row['id'])
    return {'id':row['id'],'username':row['username'],'csrf':csrf,'settings':db.settings(row['id']),'capabilities':capabilities_for(row['id']),'onboarding':onboarding.status(row['id'])}

@app.get('/api/me')
def me(user=Depends(auth.current)): return {**user,'settings':db.settings(user['id']),'capabilities':capabilities_for(user['id']),'onboarding':onboarding.status(user['id'])}

@app.get('/api/onboarding')
def setup_status(user=Depends(auth.current)):return onboarding.status(user['id'])

@app.put('/api/onboarding/sections')
def setup_section(body:onboarding.Decision,user=Depends(auth.current)):return onboarding.update(user['id'],body)

@app.post('/api/onboarding/complete')
def setup_complete(body:onboarding.Finish,user=Depends(auth.current)):return onboarding.update(user['id'],body,True)

@app.post('/api/auth/logout')
def logout(request:Request,response:Response,user=Depends(auth.current)):
    application_agent.revoke_session(user['id'],user['csrf'])
    with db.connect() as c: c.execute('DELETE FROM sessions WHERE token_hash=?',(auth.digest(request.cookies.get('next_step_session','')),))
    response.delete_cookie('next_step_session',path='/');return {'ok':True}

@app.post('/api/auth/password')
def change_password(body:PasswordChange,user=Depends(auth.current)):
    with db.connect() as c:
        row=c.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()
        if not auth.verify(row['password'],body.current): raise HTTPException(401,'Current password is incorrect.')
        c.execute('UPDATE users SET password=? WHERE id=?',(auth.hasher.hash(body.password),user['id']))
        c.execute('DELETE FROM sessions WHERE user_id=? AND csrf<>?',(user['id'],user['csrf']))
    return {'ok':True}

@app.put('/api/settings')
def update_settings(body:SettingsUpdate,user=Depends(auth.current)):
    updates=body.model_dump(exclude_none=True)
    try: ai_settings.validate_custom({**db.settings(user['id']),**updates})
    except ValueError as error: raise HTTPException(422,str(error)) from None
    return db.update_settings(user['id'],updates)

@app.put('/api/settings/openai-key')
def save_openai_key(body:OpenAIKeyUpdate,user=Depends(auth.current)):
    credentials.save(user['id'],body.api_key.get_secret_value())
    return {'configured':True,'message':'Key saved for this account. It has not been tested with OpenAI.'}

@app.delete('/api/settings/openai-key')
def remove_openai_key(user=Depends(auth.current)):
    credentials.remove(user['id'])
    return {'configured':bool(config.OPENAI_KEY and config.ALLOW_SERVER_AI_KEY),'message':'Saved account key removed.'}

@app.get('/api/usage')
def usage_history(start:str='',end:str='',model:str='',process:str='',tz:str='UTC',bucket:Literal['day','month']='day',offset:int=Query(default=0,ge=0),limit:int=Query(default=30,ge=1,le=100),user=Depends(auth.current)):
    try:return cost_history.report(user['id'],start,end,model,process,tz,bucket,offset,limit)
    except ValueError as error:raise HTTPException(422,str(error)) from None

@app.get('/api/usage/export')
def export_usage(start:str='',end:str='',model:str='',process:str='',tz:str='UTC',user=Depends(auth.current)):
    import csv,io
    try:rows,_,_=cost_history.filtered(user['id'],start,end,model,process,tz)
    except ValueError as error:raise HTTPException(422,str(error)) from None
    stream=io.StringIO();writer=csv.writer(stream)
    fields=['occurred_at','model','requested_service_tier','service_tier','process','step','status','origin','input_tokens','cached_input_tokens','cache_write_tokens','cache_write_30m_tokens','cache_write_12h_tokens','output_tokens','reasoning_tokens','web_search_calls','token_cost_usd','tool_cost_usd','estimated_cost_usd','estimated_cost_upper_usd','partial','pricing_date']
    writer.writerow(fields)
    def safe(value):
        text='' if value is None else str(value)
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    for row in rows:writer.writerow([safe(row.get(field)) for field in fields])
    return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="career-companion-cost-history.csv"','Cache-Control':'private, no-store'})

@app.get('/api/workspace')
def workspace(user=Depends(auth.current)):
    applications.migrate(user['id']);profile_answers.migrate(user['id'])
    return {kind:[applications.public(r) for r in db.list_entities(user['id'],kind)] for kind in ['experience','document','job','analysis','resume','prep','interview','assessment','assessment_progress','board','search','application','cover_letter','profile_answer','onboarding']}

from . import project_routes
project_routes.install(app,start_task,require_ai)

@app.get('/api/profile-evidence')
def confirmed_profile_evidence(user=Depends(auth.current)):
    return profile_answers.records(user['id'])

@app.get('/api/profile-answers')
def profile_answer_list(user=Depends(auth.current)):
    return profile_answers.listing(user['id'])

@app.post('/api/profile-answers/review')
def profile_answer_review(body:ProfileDraftReview,user=Depends(auth.current)):
    return profile_answers.confirm_draft(user['id'],body)

@app.put('/api/profile-answers/{entity_id}')
def profile_answer_edit(entity_id:str,body:ProfileAnswerEdit,user=Depends(auth.current)):
    return profile_answers.edit(user['id'],entity_id,body)

@app.put('/api/resume-conversations/{entity_id}/answers')
def resume_answers_save(entity_id:str,body:AnswerDraftSave,user=Depends(auth.current)):
    return question_answers.save(user['id'],entity_id,'resume',body)

@app.post('/api/resume-conversations/{entity_id}/answers/review')
async def resume_answers_review(entity_id:str,body:AnswerBatchReview,user=Depends(auth.current)):
    resume_conversation.require_initial_comparison(user['id'],entity_id)
    require_ai(user['id']);require(user['id'],entity_id,'resume_conversation')
    async def work():return await question_answers.review(user['id'],entity_id,'resume',body)
    return start_task(user['id'],'resume_guided',work,{'conversation_id':entity_id,**body.model_dump()})

@app.put('/api/cover-workspaces/{entity_id}/answers')
def cover_answers_save(entity_id:str,body:AnswerDraftSave,user=Depends(auth.current)):
    return question_answers.save(user['id'],entity_id,'cover',body)

@app.post('/api/cover-workspaces/{entity_id}/answers/review')
async def cover_answers_review(entity_id:str,body:AnswerBatchReview,user=Depends(auth.current)):
    require_ai(user['id']);require(user['id'],entity_id,'cover_workspace')
    async def work():return await question_answers.review(user['id'],entity_id,'cover',body)
    return start_task(user['id'],'cover_letter',work,{'workspace_id':entity_id,**body.model_dump()})

@app.put('/api/cover-workspaces/{entity_id}/profile-sources')
def cover_profile_sources(entity_id:str,body:CoverSourceSelection,user=Depends(auth.current)):
    def change(data,c):
        for id in body.answer_ids:
            answer=require(user['id'],id,'profile_answer')
            if answer['data']['status']!='confirmed':raise HTTPException(400,'Choose reviewed, active Profile answers.')
        data['selected_answer_ids']=list(dict.fromkeys(body.answer_ids));data['context_dirty']=True
    cover_letters.mutate(user['id'],entity_id,body.expected_version,change)
    return cover_letters.state(user['id'],entity_id)

@app.post('/api/applications/start')
def application_start(body:ApplicationStart,user=Depends(auth.current)):
    return applications.start(user['id'],body.job_id)

@app.put('/api/applications/{entity_id}/workflow')
def application_workflow(entity_id:str,body:ApplicationWorkflowUpdate,user=Depends(auth.current)):
    return applications.set_workflow(user['id'],entity_id,body)

@app.get('/api/tasks/active')
def active_tasks(user=Depends(auth.current)):
    # Metadata only: no input text, provider bodies, artifacts or result records.
    with db.connect() as c:
        rows=c.execute("SELECT id,kind,status,result,created_at,updated_at FROM tasks WHERE user_id=? AND status IN ('queued','running') ORDER BY created_at",(user['id'],)).fetchall()
    return [{**{k:row[k] for k in ('id','kind','status','created_at','updated_at')},'progress':json.loads(row['result'] or '{}').get('_task_progress')} for row in rows]

@app.get('/api/tasks/{task_id}')
def get_task(task_id:str,user=Depends(auth.current)):
    with db.connect() as c: row=c.execute('SELECT * FROM tasks WHERE id=? AND user_id=?',(task_id,user['id'])).fetchone()
    if not row: raise HTTPException(404,'Task not found.')
    result=dict(row);result['result']=json.loads(result['result']) if result['result'] else None
    payload=result['result'] if isinstance(result['result'],dict) else {}
    inputs=payload.get('_task_inputs',payload.get('inputs',{}))
    if inputs.get('operation') in ('document_upload','posting_upload') and db.get(user['id'],inputs.get('job_id',''),'job'):
        result['job_id']=inputs['job_id']
    result['progress']=result['result'].pop('_task_progress',None) if isinstance(result['result'],dict) else None
    if isinstance(result['result'],dict) and '_task_result' in result['result']:result['result']=result['result']['_task_result']
    return result

@app.get('/api/analyses/{entity_id}/role-alignment')
def get_role_alignment(entity_id:str,user=Depends(auth.current)):
    from . import role_alignment
    analysis=require(user['id'],entity_id,'analysis')['data']
    posting=analysis.get('posting_snapshot') or require(user['id'],analysis['job_id'],'job')['data']
    duties=role_alignment.rows(analysis,posting)
    return {'duties':duties,'assessed':analysis.get('duty_alignment_version')==role_alignment.VERSION and all(r.get('assessment_complete') for r in duties),'version':role_alignment.VERSION}

@app.post('/api/experience')
def add_experience(body:ExperienceItem,user=Depends(auth.current)):
    certifications.validate_documents(user['id'],body.model_dump())
    return db.save(user['id'],'experience',body.model_dump())

@app.put('/api/experience/{entity_id}')
def edit_experience(entity_id:str,body:ExperienceItem,user=Depends(auth.current)):
    require(user['id'],entity_id,'experience')
    certifications.validate_documents(user['id'],body.model_dump())
    return db.save(user['id'],'experience',body.model_dump(),entity_id)

@app.delete('/api/records/{entity_id}')
def remove_record(entity_id:str,user=Depends(auth.current)):
    record=db.get(user['id'],entity_id)
    if not record: raise HTTPException(404,'Record not found.')
    blocker=application_documents.removal_blocker(user['id'],record)
    if blocker:raise HTTPException(409,blocker)
    if record['kind']=='usage_event':raise HTTPException(409,'Cost history is preserved until account deletion.')
    if record['kind'] in ('onboarding','profile_answer','project_source','project_snapshot','project_analysis','answer_draft','work_style','story_prompts'):raise HTTPException(409,'Archive reviewed answers to preserve their source history.')
    if record['kind'] in ('job','analysis','resume','resume_draft','resume_revision','resume_conversation','application','cover_workspace','cover_revision','cover_letter','prep','interview','search'):onboarding.require_complete(user['id'])
    if record['kind']=='document':
        if record['data'].get('purpose')=='certificate' and any(v.get('document_id')==entity_id for row in db.list_entities(user['id'],'experience') for v in row['data'].get('certification_items',[])):
            raise HTTPException(409,'Remove this attachment from its certification before deleting the file.')
        file=config.DATA_DIR/'uploads'/user['id']/entity_id
        file.unlink(missing_ok=True)
    db.delete(user['id'],entity_id);return {'ok':True}

@app.post('/api/jobs/import-document')
async def import_job_document(file:UploadFile=File(...),user=Depends(auth.current)):
    filename=Path(file.filename or 'job-posting.pdf').name[:250]
    is_pdf=Path(filename).suffix.lower()=='.pdf'
    limit=50*1024*1024 if is_pdf else config.MAX_UPLOAD
    raw=await file.read(limit+1)
    extracted=await asyncio.to_thread(documents.extract,filename,raw,max_upload=limit,repair_font_mappings=is_pdf)
    # Filename hints are editable, not verified employer data. Keep all text so
    # browser print headers/navigation never silently remove qualifications.
    identity=job_parser.document_identity(filename,extracted['text'])
    title,company=identity['title'],identity['company']
    overview=job_parser.organize({'title':title,'company':company,'description':extracted['text']})
    overview['identity_sources']=identity['identity_sources']
    return {'title':title,'company':company,'description':extracted['text'],'url':'',
            'filename':filename,'pages':extracted['pages'],'overview':overview,
            'note':'Check the title, company, and description before saving. Titles and companies may use filename hints. The uploaded file is not stored.'}

@app.post('/api/transcripts/parse')
async def parse_transcript(file:UploadFile=File(...),user=Depends(auth.current)):
    raw=await file.read(config.MAX_UPLOAD+1)
    extracted=await asyncio.to_thread(documents.extract,Path(file.filename or 'transcript.txt').name[:200],raw)
    # Parse transiently: transcripts may contain student IDs and grades. Only
    # explicitly selected course names enter the education draft in the browser.
    return transcript_parser.parse(extracted['text'])

@app.post('/api/certificates')
async def upload_certificate(file:UploadFile=File(...),user=Depends(auth.current)):
    raw=await file.read(10*1024*1024+1)
    filename=Path(file.filename or 'certificate').name[:200]
    mime=await asyncio.to_thread(certifications.inspect_file,filename,raw)
    digest=hashlib.sha256(raw).hexdigest()
    for existing in db.list_entities(user['id'],'document'):
        if existing['data'].get('purpose')=='certificate' and existing['data'].get('sha256')==digest and (config.DATA_DIR/'uploads'/user['id']/existing['id']).is_file(): return existing
    record=db.save(user['id'],'document',{'filename':filename,'purpose':'certificate','mime':mime,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'text':'','reviewed':False})
    folder=config.DATA_DIR/'uploads'/user['id'];folder.mkdir(parents=True,exist_ok=True)
    (folder/record['id']).write_bytes(raw)
    return record

@app.post('/api/certificates/{entity_id}/extract')
async def extract_certificate(entity_id:str,user=Depends(auth.current)):
    from . import certificate_parser
    record=require(user['id'],entity_id,'document')
    if record['data'].get('purpose')!='certificate': raise HTTPException(404,'Certificate not found.')
    if record['data'].get('mime')!='application/pdf': raise ServiceError('Automatic extraction supports text-based PDFs. Enter image certificate details manually.')
    path=config.DATA_DIR/'uploads'/user['id']/entity_id
    if not path.is_file(): raise HTTPException(404,'Certificate file unavailable.')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=record['data']['sha256']: raise HTTPException(409,'The saved certificate changed. Upload it again before extracting details.')
    result=await asyncio.to_thread(certificate_parser.parse_pdf,raw)
    return {**result,'document_id':entity_id,'sha256':record['data']['sha256']}

@app.get('/api/certificates/{entity_id}/download')
def certificate_download(entity_id:str,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'document')
    if record['data'].get('purpose')!='certificate': raise HTTPException(404,'Certificate not found.')
    path=config.DATA_DIR/'uploads'/user['id']/entity_id
    if not path.is_file(): raise HTTPException(404,'Certificate file unavailable.')
    return FileResponse(path,media_type='application/octet-stream',filename=record['data']['filename'],headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

@app.post('/api/documents')
async def import_document(file:UploadFile=File(...),purpose:Literal['source','resume']='source',user=Depends(auth.current)):
    raw=await file.read(config.MAX_UPLOAD+1)
    filename=Path(file.filename or 'document.txt').name[:200]
    extracted=await asyncio.to_thread(documents.extract,filename,raw)
    parsed=resume_parser.parse(extracted['text']) if purpose=='resume' else None
    if parsed: parsed['profile_base']={k:db.settings(user['id']).get(k,'') for k in parsed['profile']}
    entity=db.save(user['id'],'document',{'filename':filename,**extracted,'reviewed':False,'sha256':hashlib.sha256(raw).hexdigest(),'resume_parse':parsed})
    folder=config.DATA_DIR/'uploads'/user['id'];folder.mkdir(parents=True,exist_ok=True)
    (folder/entity['id']).write_bytes(raw)
    return entity

class DocumentReview(StrictModel):
    text:str=Field(min_length=1,max_length=100000)

@app.put('/api/documents/{entity_id}/review')
def review_document(entity_id:str,body:DocumentReview,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'document')
    if record['data'].get('purpose')=='application':raise HTTPException(400,'Review application resume text within its application.')
    return db.save(user['id'],'document',{**record['data'],'text':body.text,'reviewed':True},entity_id)

@app.post('/api/documents/{entity_id}/parse')
def parse_resume_document(entity_id:str,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'document');data=dict(record['data'])
    if record['data'].get('purpose') in ('certificate','application'): raise HTTPException(400,'Manage this document in its original application or certification.')
    text=data['text']
    if data.get('format')=='docx' and not data.get('reviewed'):
        path=config.DATA_DIR/'uploads'/user['id']/entity_id
        if path.exists(): text=documents.enrich_docx_links(text,path.read_bytes())
    signature=hashlib.sha256(text.encode()).hexdigest()
    cached=data.get('resume_parse') or {}
    base={k:db.settings(user['id']).get(k,'') for k in cached.get('profile',{})}
    if cached.get('text_hash')==signature and cached.get('parser_version')==resume_parser.VERSION:
        if cached.get('profile_base')==base: return record
        cached['profile_base']=base
        return db.save(user['id'],'document',{**data,'resume_parse':cached},entity_id)
    parsed=resume_parser.parse(text)
    parsed['profile_base']={k:db.settings(user['id']).get(k,'') for k in parsed['profile']}
    return db.save(user['id'],'document',{**data,'text':text,'resume_parse':parsed},entity_id)

@app.post('/api/documents/{entity_id}/import-resume')
def approve_resume_import(entity_id:str,body:ResumeImportApproval,user=Depends(auth.current)):
    # Approval is one atomic operation. Other master records and versions are
    # never overwritten; repeated submissions skip already imported entries.
    for proposal in body.entries: certifications.validate_documents(user['id'],proposal.data.model_dump())
    updates=body.profile_updates.model_dump(exclude_none=True)
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='document'",(entity_id,user['id'])).fetchone()
        if not row: raise HTTPException(404,'Document not found.')
        document=json.loads(row['payload'])
        if document.get('purpose')=='application':raise HTTPException(400,'Application files are not Profile imports.')
        parsed=document.get('resume_parse') or {}
        if body.text_hash!=parsed.get('text_hash') or hashlib.sha256(document['text'].encode()).hexdigest()!=body.text_hash:
            raise HTTPException(409,'The source changed. Parse the updated text and review its suggestions again.')
        allowed={entry['id'] for entry in parsed.get('entries',[])}
        if len({e.id for e in body.entries})!=len(body.entries) or any(e.id not in allowed for e in body.entries): raise HTTPException(400,'An entry does not belong to this document review.')
        if any(key not in parsed.get('profile',{}) for key in updates): raise HTTPException(400,'Only proposed contact fields can be imported here. Use Personal Details for other changes.')
        profile=json.loads(c.execute('SELECT settings FROM users WHERE id=?',(user['id'],)).fetchone()[0])
        for key in updates:
            if profile.get(key,'') not in (parsed.get('profile_base',{}).get(key,''),updates[key]):
                raise HTTPException(409,'Your personal details changed during review. Reopen the document to review the current values.')
        rows=c.execute("SELECT * FROM entities WHERE user_id=? AND kind='experience'",(user['id'],)).fetchall()
        existing=[(r['id'],json.loads(r['payload'])) for r in rows]
        source_ids={data.get('source_entry_id'):identity for identity,data in existing if data.get('source_entry_id')}
        fingerprints={resume_parser.fingerprint(data):identity for identity,data in existing}
        created=[];skipped=[];stamp=db.now()
        for proposal in body.entries:
            data={**proposal.data.model_dump(),'confirmed':True,'source_document_id':entity_id,'source_entry_id':proposal.id}
            digest=resume_parser.fingerprint(data)
            duplicate=source_ids.get(proposal.id) or fingerprints.get(digest)
            if duplicate: skipped.append({'entry_id':proposal.id,'record_id':duplicate});continue
            identity=db.uid();raw=json.dumps(data)
            c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?)',(identity,user['id'],'experience',raw,stamp,stamp))
            c.execute('INSERT INTO evidence_fts VALUES(?,?,?,?)',(identity,user['id'],'experience',raw))
            onboarding.profile_added(c,user['id'],'experience',data)
            created.append({'entry_id':proposal.id,'record_id':identity});source_ids[proposal.id]=identity;fingerprints[digest]=identity
        profile.update(updates)
        c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps(profile),user['id']))
        document.update(reviewed=True,last_resume_import={'created':created,'skipped':skipped,'profile_fields':list(updates),'imported_at':stamp})
        c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=?',(json.dumps(document),stamp,entity_id))
    return {'created':len(created),'skipped':len(skipped),'profile_fields':list(updates),'message':f"Imported {len(created)} confirmed records. Skipped {len(skipped)} duplicates. Existing records and saved resumes were preserved."}

@app.post('/api/jobs')
def add_job(body:JobPosting,user=Depends(auth.current)):
    if body.url and not integrations.canonical_url(body.url): raise HTTPException(422,'Use a public HTTP(S) posting URL or leave the URL blank.')
    return db.save(user['id'],'job',body.model_dump())

@app.post('/api/jobs/parse')
def parse_job(body:JobPosting,user=Depends(auth.current)):
    return job_parser.organize(body.model_dump())

@app.get('/api/jobs/{entity_id}/overview')
def job_overview(entity_id:str,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'job')
    return job_parser.organize(record['data'])

@app.put('/api/jobs/{entity_id}')
def update_job(entity_id:str,body:JobPosting,user=Depends(auth.current)):
    previous=require(user['id'],entity_id,'job')
    if body.url and not integrations.canonical_url(body.url): raise HTTPException(422,'Use a public HTTP(S) posting URL or leave the URL blank.')
    data=body.model_dump()
    if body.description==previous['data']['description'] and posting_extraction.cached(previous['data']):
        data['structured_posting']=previous['data']['structured_posting']
    return db.save(user['id'],'job',data,entity_id)

@app.post('/api/jobs/import-url')
async def import_url(body:ImportURL,user=Depends(auth.current)):
    page=await public_fetch(body.url)
    if page['status']!=200: raise ServiceError('This page did not return a readable posting. Paste the text instead.')
    if 'html' not in page['content_type']: raise ServiceError('Use a public HTML posting URL, or upload its document.')
    parsed=html_job(page['content'])
    if len(parsed['description'])<10: raise ServiceError('No readable description was found. Paste the posting instead.')
    return {'title':parsed['title'],'company':parsed['company'],'description':parsed['description'],'url':page['url'],'review_required':True}

@app.post('/api/analyses')
async def analyze_job(body:AnalysisRequest,user=Depends(auth.current)):
    require_ai(user['id']);job=require(user['id'],body.job_id,'job')
    async def work():
        prepared=await posting_extraction.prepare_saved(user['id'],job,body.mode)
        task_progress.stage('comparing_profile')
        result=await ai.analyze(user['id'],prepared['data'],body.mode)
        task_progress.stage('saving_comparison')
        return db.save(user['id'],'analysis',{**result,'job_id':job['id']})
    return start_task(user['id'],'analysis',work,body.model_dump())


@app.get('/api/analyses/from-document/status')
def document_comparison_status(request_token:str=Query(min_length=8,max_length=100),user=Depends(auth.current)):
    return upload_task_status(request_token,user,'analysis','document_upload')

def upload_task_status(request_token,user,kind,operation):
    with db.connect() as c:
        rows=c.execute("SELECT id,status,result FROM tasks WHERE user_id=? AND kind=? ORDER BY created_at DESC",(user['id'],kind)).fetchall()
    for row in rows:
        payload=json.loads(row['result'] or '{}')
        inputs=payload.get('_task_inputs',payload.get('inputs',{}))
        if inputs.get('operation')==operation and inputs.get('request_token')==request_token:
            return {'task_id':row['id'],'status':row['status']}
    raise HTTPException(404,'No comparison was started for this upload. Select the document to try again.')


@app.get('/api/jobs/from-document/status')
def posting_upload_status(request_token:str=Query(min_length=8,max_length=100),user=Depends(auth.current)):
    return upload_task_status(request_token,user,'posting_import','posting_upload')

@app.post('/api/jobs/from-document')
async def posting_upload(file:UploadFile=File(...),mode:Literal['economy','deep','custom']=Form('economy'),request_token:str=Form(min_length=8,max_length=100),user=Depends(auth.current)):
    return await analyze_document(file,mode,request_token,user,False)

@app.post('/api/analyses/from-document')
async def analyze_document(file:UploadFile=File(...),mode:Literal['economy','deep','custom']=Form('economy'),
                           request_token:str=Form(min_length=8,max_length=100),user=Depends(auth.current),compare_profile:bool=True):
    require_ai(user['id'])
    if compare_profile and not profile_answers.records(user['id']):
        raise HTTPException(400,'Add confirmed Profile experience before starting a comparison.')
    filename=Path(file.filename or 'job-posting.pdf').name[:250]
    is_pdf=Path(filename).suffix.lower()=='.pdf'
    limit=50*1024*1024 if is_pdf else config.MAX_UPLOAD
    raw=await file.read(limit+1)
    if is_pdf:
        context=ai.set_user_context(user['id'])
        try:posting_extraction.require_pdf_model(mode)
        finally:ai.reset_user_context(context)
    extracted=await asyncio.to_thread(documents.extract,filename,raw,max_upload=limit,repair_font_mappings=is_pdf)
    if is_pdf and len(raw)>=50*1024*1024:
        raise ServiceError('Choose a PDF smaller than 50 MB for AI comparison.')
    digest=hashlib.sha256(raw).hexdigest()
    job_id=hashlib.sha256((user['id']+'\0document\0'+request_token).encode()).hexdigest()[:32]
    inputs={'request_token':request_token,'operation':'document_upload' if compare_profile else 'posting_upload','mode':mode,
            'filename':filename,'document_hash':digest,'job_id':job_id}

    async def work():
        nonlocal raw
        job={'title':'','company':'','description':extracted['text'],'url':''}
        try:
            overview=await posting_extraction.extract(job,mode,filename=filename,raw=raw,document_hash=digest)
        finally:
            raw=None
        data={**job,'title':overview['title'],'company':overview['company'],'structured_posting':overview}
        saved=db.save(user['id'],'job',data,job_id)
        if not compare_profile:return saved
        task_progress.stage('comparing_profile')
        result=await ai.analyze(user['id'],saved['data'],mode)
        task_progress.stage('saving_comparison')
        return db.save(user['id'],'analysis',{**result,'job_id':saved['id']})

    return start_task(user['id'],'analysis' if compare_profile else 'posting_import',work,inputs)

SECTION_NAMES={'education':'Education','coursework':'Relevant Coursework','project':'Projects','employment':'Work Experience','volunteering':'Volunteering','skills':'Skills'}

def build_resume(user,body):
    available={r['id']:r for r in profile_answers.records(user)}
    ids=list(dict.fromkeys(body.experience_ids))
    if not ids: raise HTTPException(400,'Select at least one confirmed Profile record.')
    if any(i not in available for i in ids): raise HTTPException(400,'Select only your confirmed Profile records.')
    analysis=require(user,body.analysis_id,'analysis') if body.analysis_id else None
    if analysis and body.job_id and analysis['data'].get('job_id')!=body.job_id: raise HTTPException(409,'Choose a comparison for this posting.')
    suggestions=analysis['data'].get('suggestions',[]) if analysis else []
    decisions={d.index:d for d in body.decisions}
    if any(i>=len(suggestions) for i in decisions): raise HTTPException(400,'An edit does not belong to this analysis.')
    entries=[];warnings=[]
    # Build all confirmed records to keep source checks independent of current selection.
    for entity_id,record in available.items():
        data=record['data'];entry=resume_data.entry_snapshot(data,entity_id,granular=True)
        entry['source_original_bullets']=list(entry['bullets'])
        entry['reviewed_answer_sources']=data.get('answer_sources',[])
        for index,suggestion in enumerate(suggestions):
            decision=decisions.get(index)
            if suggestion['record_id']!=entity_id or not decision or decision.action=='reject':continue
            if not ai.valid_quote(suggestion['original'],ai.experience_text(data)): raise HTTPException(409,'The Profile changed after this comparison. Rerun it before applying these edits.')
            replacement=suggestion['proposed'] if decision.action=='accept' else decision.text.strip()
            if not replacement:continue
            matches=[i for i,v in enumerate(entry['bullets']) if suggestion['original'] in v]
            if matches:
                i=matches[0];entry['bullets'][i]=entry['bullets'][i].replace(suggestion['original'],replacement,1);entry['content_items'][i]['text']=entry['bullets'][i]
            else:
                matches=[i for i,v in enumerate(entry['content_items']) if ai.normalized(re.sub(r'^Relevant class: ','',v['original'])) in ai.normalized(suggestion['original'])]
                if not matches:raise HTTPException(409,'This edit no longer maps to source content. Rerun the comparison.')
                for i in matches:
                    entry['bullets'][i]=replacement if i==matches[0] else ''
                    entry['content_items'][i]['text']=entry['bullets'][i]
        entry['content_items']=[i for i in entry['content_items'] if i['text'].strip()]
        entry['bullets']=[i['text'] for i in entry['content_items']]
        if not entry['dates'] and data['category'] in ('education','employment','volunteering') and entity_id in ids:warnings.append(data['title']+': dates not provided.')
        entries.append(entry)
    order=['education','employment','project','volunteering','coursework','skills'] if body.template=='education' else ['employment','project','volunteering','education','coursework','skills']
    profile=db.settings(user)
    if not profile.get('name'):warnings.append('Name not provided; export will use Resume as its title.')
    contact_lines=resume_data.contact_lines(profile)
    if not contact_lines:warnings.append('Contact information not provided.')
    job_id=body.job_id or (analysis['data'].get('job_id') if analysis else None)
    job=require(user,job_id,'job') if job_id else None
    snapshot={'schema_version':3,'compact_skills':body.compact_skills,'job_id':job_id,'posting_snapshot':dict(job['data']) if job else {},'content':body.content,'title':resume_data.resume_title(job['data'] if job else {},body.title,profile.get('name') or ''),'template':body.template,'name':documents.clean(profile.get('name')),'headline':documents.clean(profile.get('headline')),'contact':'\n'.join(contact_lines),'contact_lines':contact_lines,'profile':{k:profile.get(k) for k in ('name','contact','contact_reviewed','headline','email','phone','city','state','country','county','website','linkedin')},'sections':[{'title':SECTION_NAMES[k],'entries':[e for e in entries if e['category']==k]} for k in order],'warnings':warnings,'experience_ids':ids,'analysis_id':body.analysis_id,'decisions':[d.model_dump() for d in body.decisions],'ai':analysis['data'].get('ai') if analysis else None}
    if body.draft_id:
        draft=require(user,body.draft_id,'resume_draft')['data']
        if draft.get('posting_hash') and draft['posting_hash']!=job_parser.posting_hash(snapshot['posting_snapshot']):raise HTTPException(409,'The posting changed after this draft. Create a new draft; the previous one remains available.')
        if draft['job_id']!=job_id:raise HTTPException(409,'Choose the AI draft for this posting.')
        if draft['source_fingerprint']!=optimization.fingerprint(snapshot,{r['id'] for r in draft['catalog']}):raise HTTPException(409,'Profile content changed since this AI draft. Create a new draft; your reviewed wording remains available.')
        snapshot=optimization.apply(snapshot,draft,body.overrides)
        snapshot.update({'draft_id':body.draft_id,'optimization':{'ai':draft['ai'],'audit_ai':draft['audit_ai'],'actual_cost_usd':draft['actual_cost_usd'],'source_checked':True,'headline_evidence':draft['headline_evidence'],'omitted':draft['omitted'],'keywords':draft['keywords']}})
    elif body.overrides:
        # Manual content editing uses the same stable source IDs and limits.
        snapshot=optimization.apply(snapshot,{'entries':[],'headline':snapshot['headline']},body.overrides)
    if body.headline is not None:snapshot['headline']=documents.clean(body.headline)
    snapshot['profile']['headline']=snapshot['headline']
    if body.content is not None:
        for entity_id,chosen in body.content.items():
            if entity_id not in available:raise HTTPException(400,'Content selections must belong to your confirmed Profile.')
            length=len(next(e['bullets'] for e in entries if e['source_id']==entity_id))
            if len(chosen)!=len(set(chosen)) or any(i<0 or i>=length for i in chosen):raise HTTPException(409,'Selected content changed. Refresh the content list before saving.')
    parts=body.content if body.content is not None else {e['source_id']:list(range(len(e['bullets']))) for e in entries}
    return resume_builder.select(snapshot,parts,ids)

def save_one_page(user,body):
    snapshot=build_resume(user,body)
    missing=set(body.experience_ids)-set(snapshot['experience_ids'])
    if missing:raise ServiceError('A selected record has no content. Select its descriptive content or uncheck the record before saving.')
    if not any(s['entries'] for s in snapshot['sections']):raise ServiceError('Select meaningful resume content before saving. Empty headings are omitted.')
    for section in snapshot['sections']:
        for entry in section['entries']:
            if entry['category']=='project' and not any(i['field'] in ('description','contribution','accomplishment') for i in entry.get('content_items',[])):raise ServiceError('Include a descriptive bullet for '+entry['title']+' or omit that project.')
    pages,artifacts=resume_builder.render(snapshot)
    if pages!=1:
        longest=sorted([e for s in snapshot['sections'] for e in s['entries']],key=lambda e:-sum(len(b) for b in e['bullets']))[:3]
        names=', '.join(e['title'] for e in longest)
        raise ServiceError(f'This selection fills {pages} pages. The longest sections to review are: {names}. Shorten their wording, uncheck lower-priority items, or use Fit content locally. Nothing was saved, clipped, or silently rewritten.')
    snapshot.update({'layout':{'pages':1,'body_font_pt':10.5,'validated':True},'artifacts':artifacts})
    record=db.save(user,'resume',snapshot)
    applications.attach_resume(user,record)
    return applications.public(record)

@app.post('/api/resumes')
def create_resume(body:ResumeRequest,user=Depends(auth.current)):
    return save_one_page(user['id'],body)

@app.post('/api/resumes/save')
async def create_resume_task(body:ResumeRequest,user=Depends(auth.current)):
    async def work(): return await asyncio.to_thread(save_one_page,user['id'],body)
    return start_task(user['id'],'resume',work,body.model_dump())

@app.post('/api/resume-content')
def resume_content(body:ResumeRequest,user=Depends(auth.current)):
    full=body.model_copy(update={'content':None})
    snapshot=build_resume(user['id'],full)
    analysis=require(user['id'],body.analysis_id,'analysis')['data'] if body.analysis_id else None
    return {'catalog':resume_builder.catalog(snapshot,analysis)}

@app.post('/api/resumes/fit')
async def fit_resume(body:ResumeRequest,user=Depends(auth.current)):
    # Saved inputs live in the task record even if the converter fails or restarts.
    snapshot=build_resume(user['id'],body.model_copy(update={'content':None}))
    analysis=require(user['id'],body.analysis_id,'analysis')['data'] if body.analysis_id else None
    rows=resume_builder.catalog(snapshot,analysis)
    async def work(): return await asyncio.to_thread(resume_builder.fit,snapshot,rows,{'experience_ids':body.experience_ids,'content':body.content} if body.content is not None else None)
    return start_task(user['id'],'resume_fit',work,body.model_dump())

@app.post('/api/resumes/optimize-estimate')
def optimize_estimate(body:OptimizationRequest,user=Depends(auth.current)):
    full=body.model_copy(update={'experience_ids':[r['id'] for r in db.list_entities(user['id'],'experience') if r['data'].get('confirmed')],'content':None,'draft_id':None,'overrides':{},'headline':None})
    return optimization.estimate(build_resume(user['id'],full),body.mode,db.settings(user['id']))

@app.post('/api/resumes/optimize')
async def optimize_resume(body:OptimizationRequest,user=Depends(auth.current)):
    require_ai(user['id'])
    if not body.job_id:raise HTTPException(400,'Choose a job posting before optimizing.')
    all_ids=[r['id'] for r in db.list_entities(user['id'],'experience') if r['data'].get('confirmed')]
    feedback={}
    if body.draft_id:
        old=require(user['id'],body.draft_id,'resume_draft')
        if old['data']['job_id']!=body.job_id:raise HTTPException(409,'This draft belongs to a different posting.')
        feedback={'headline':body.headline,'selected_records':body.experience_ids,'selected_items':body.content,'reviewed_text':body.overrides}
    full=body.model_copy(update={'experience_ids':all_ids,'content':None,'draft_id':None,'overrides':{},'headline':None})
    snapshot=build_resume(user['id'],full)
    analysis=require(user['id'],body.analysis_id,'analysis')['data'] if body.analysis_id else None
    if analysis and analysis.get('posting_hash') and analysis['posting_hash']!=job_parser.posting_hash(snapshot['posting_snapshot']):raise HTTPException(409,'The posting changed. Rerun its comparison before creating an AI draft.')
    if analysis and analysis.get('schema_version')!=3:raise HTTPException(409,'Rerun the historical comparison, or build without it, before creating an AI draft.')
    async def work():return await optimization.create(user['id'],snapshot,analysis,body.mode,feedback)
    return start_task(user['id'],'resume_optimize',work,body.model_dump())

@app.post('/api/resume-conversations')
def resume_conversation_start(body:ConversationStart,user=Depends(auth.current)):
    return resume_conversation.start(user['id'],body)

@app.get('/api/resume-conversations/{entity_id}')
def resume_conversation_get(entity_id:str,user=Depends(auth.current)):
    return resume_conversation.state(user['id'],entity_id)

@app.get('/api/resume-conversations/{entity_id}/estimate')
def resume_conversation_estimate(entity_id:str,mode:str='economy',user=Depends(auth.current)):
    if mode not in ('economy','deep','custom'):raise HTTPException(400,'Choose a valid AI mode.')
    return resume_conversation.estimate(user['id'],entity_id,mode)

@app.post('/api/resume-conversations/{entity_id}/build')
async def resume_conversation_build(entity_id:str,body:GuidedBuild,manual:bool=False,user=Depends(auth.current)):
    resume_conversation.require(user['id'],entity_id,'resume_conversation')
    if not manual:
        resume_conversation.require_initial_comparison(user['id'],entity_id);require_ai(user['id'])
    async def work():return await resume_conversation.build(user['id'],entity_id,body.expected_version,body.mode,body.decisions,body.template,manual=manual,preparation=body.preparation)
    return start_task(user['id'],'resume_guided',work,{'conversation_id':entity_id,**body.model_dump()})

@app.post('/api/resume-conversations/{entity_id}/messages')
async def resume_conversation_send(entity_id:str,body:ConversationMessage,user=Depends(auth.current)):
    resume_conversation.require_initial_comparison(user['id'],entity_id)
    require_ai(user['id']);resume_conversation.require(user['id'],entity_id,'resume_conversation')
    async def work():return await resume_conversation.send(user['id'],entity_id,body)
    return start_task(user['id'],'resume_guided',work,{'conversation_id':entity_id,**body.model_dump()})

@app.post('/api/resume-conversations/{entity_id}/approve')
async def resume_conversation_approve(entity_id:str,body:FactApproval,user=Depends(auth.current)):
    record=resume_conversation.require(user['id'],entity_id,'resume_conversation')
    update=body.action=='approve' and body.update_draft and bool(record['data'].get('current_revision_id'))
    if update:require_ai(user['id'])
    state=resume_conversation.approve(user['id'],entity_id,body)
    if not update:return {'cached':True,'result':state}
    async def work():return await resume_conversation.build(user['id'],entity_id,state['data']['version'],body.mode)
    return start_task(user['id'],'resume_guided',work,{'conversation_id':entity_id,**body.model_dump()})

@app.post('/api/resume-conversations/{entity_id}/adopt')
async def resume_conversation_adopt(entity_id:str,body:LegacyDraftLoad,user=Depends(auth.current)):
    resume_conversation.require(user['id'],entity_id,'resume_conversation')
    async def work():return await asyncio.to_thread(resume_conversation.adopt,user['id'],entity_id,body)
    return start_task(user['id'],'resume_guided',work,{'conversation_id':entity_id,**body.model_dump()})

@app.post('/api/resume-conversations/{entity_id}/render')
async def resume_conversation_render(entity_id:str,body:WorkingRender,user=Depends(auth.current)):
    resume_conversation.require(user['id'],entity_id,'resume_conversation')
    async def work():return await asyncio.to_thread(resume_conversation.render,user['id'],entity_id,body)
    return start_task(user['id'],'resume_guided',work,{'conversation_id':entity_id,**body.model_dump()})

@app.post('/api/resume-conversations/{entity_id}/restore')
def resume_conversation_restore(entity_id:str,body:RevisionAction,user=Depends(auth.current)):
    return resume_conversation.restore(user['id'],entity_id,body)

@app.post('/api/resume-conversations/{entity_id}/finalize')
def resume_conversation_finalize(entity_id:str,body:FinalizeRevision,user=Depends(auth.current)):
    return resume_conversation.finalize(user['id'],entity_id,body)

@app.get('/api/resume-revisions/{entity_id}/pages/{page}')
def resume_revision_page(entity_id:str,page:int,user=Depends(auth.current)):
    revision=resume_conversation.require(user['id'],entity_id,'resume_revision')['data']
    snapshot=revision['snapshot']
    if page<1 or page>snapshot['layout']['pages']:raise HTTPException(404,'Page not found.')
    return Response(documents.pdf_preview(base64.b64decode(snapshot['artifacts']['pdf']),page),media_type='image/png',headers={'Cache-Control':'private, max-age=31536000, immutable'})

@app.get('/api/resume-drafts')
def resume_drafts(job_id:str,user=Depends(auth.current)):
    require(user['id'],job_id,'job')
    return [{'id':r['id'],'kind':r['kind'],'created_at':r['created_at'],'updated_at':r['updated_at'],'data':{'job_id':r['data']['job_id'],'ai':r['data']['ai'],'guided':bool(r['data'].get('rendered_snapshot'))}} for r in db.list_entities(user['id'],'resume_draft') if r['data'].get('job_id')==job_id]

@app.get('/api/resume-drafts/{entity_id}')
def get_resume_draft(entity_id:str,user=Depends(auth.current)):
    return resume_conversation.public(require(user['id'],entity_id,'resume_draft'))

@app.post('/api/resumes/keywords')
def keyword_coverage(body:ResumeRequest,user=Depends(auth.current)):
    draft=require(user['id'],body.draft_id,'resume_draft')['data'] if body.draft_id else None
    analysis=require(user['id'],body.analysis_id,'analysis')['data'] if body.analysis_id else None
    if draft and draft['job_id']!=body.job_id:raise HTTPException(409,'Choose a draft for this posting.')
    keywords=(draft or analysis or {}).get('keywords',[])
    text=''
    if body.experience_ids:text=documents.resume_plain(build_resume(user['id'],body))
    groups={'included':[],'supported':[],'unknown':[]}
    for keyword in keywords:
        found=bool(re.search(r'(?<![\w])'+re.escape(keyword['term'])+r'(?![\w])',text,re.I))
        key='unknown' if not keyword['evidence'] else 'included' if found else 'supported'
        groups[key].append(keyword)
    return groups

@app.get('/api/resumes/{entity_id}/preview-image')
def preview_resume_image(entity_id:str,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'resume')
    if record['data'].get('origin')=='uploaded':
        document,raw=application_documents.uploaded_original(user['id'],record)
        if document['data']['mime']!='application/pdf':raise HTTPException(400,'Download the original file to view this format.')
    else:raw,_=documents.export_resume(record['data'],'pdf')
    return Response(documents.pdf_preview(raw),media_type='image/png')

@app.get('/api/resumes/{entity_id}/preview')
def preview_resume(entity_id:str,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'resume')
    if record['data'].get('origin')=='uploaded':
        document,raw=application_documents.uploaded_original(user['id'],record)
        if document['data']['mime']!='application/pdf':raise HTTPException(400,'Download the original file to view this format.')
        return application_documents.response_file(raw,document['data']['filename'],document['data']['mime'],True)
    raw,mime=documents.export_resume(record['data'],'pdf')
    return Response(raw,media_type=mime,headers={'Content-Disposition':'inline; filename="resume.pdf"'})

@app.get('/api/resumes/{entity_id}/export/{format}')
def export(entity_id:str,format:str,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'resume')
    if record['data'].get('schema_version')==2 and record['data'].get('layout',{}).get('pages')!=1: raise ServiceError('Save a validated one-page version before exporting.')
    if record['data'].get('origin')=='uploaded':
        document,raw=application_documents.uploaded_original(user['id'],record)
        if format!='original' and '.'+format!=Path(document['data']['filename']).suffix.lower():raise HTTPException(400,'Download the original uploaded format; no converted version is implied.')
        return application_documents.response_file(raw,document['data']['filename'],document['data']['mime'])
    raw,mime=documents.export_resume(record['data'],format)
    filename=resume_data.resume_filename(record['data'],format)
    fallback=re.sub(r'[^a-zA-Z0-9 ._-]','_',filename)
    return Response(raw,media_type=mime,headers={'Content-Disposition':f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename,safe='')}"})

@app.post('/api/cover-letters/workspace')
def cover_start(body:CoverStart,user=Depends(auth.current)):
    return cover_letters.start(user['id'],body)

@app.get('/api/cover-workspaces/{entity_id}')
def cover_workspace(entity_id:str,user=Depends(auth.current)):
    return cover_letters.state(user['id'],entity_id)

@app.get('/api/cover-workspaces/{entity_id}/estimate')
def cover_estimate(entity_id:str,mode:Literal['economy','deep','custom']='economy',user=Depends(auth.current)):
    return cover_letters.estimate(user['id'],entity_id,mode)

@app.post('/api/cover-workspaces/{entity_id}/generate')
async def cover_generate(entity_id:str,body:CoverGenerate,user=Depends(auth.current)):
    require_ai(user['id']);require(user['id'],entity_id,'cover_workspace')
    async def work():return await cover_letters.generate(user['id'],entity_id,body)
    return start_task(user['id'],'cover_letter',work,{'workspace_id':entity_id,'operation':'generate',**body.model_dump()})

@app.post('/api/cover-workspaces/{entity_id}/questions')
async def cover_questions(entity_id:str,body:CoverGenerate,user=Depends(auth.current)):
    require_ai(user['id']);require(user['id'],entity_id,'cover_workspace')
    async def work():return await cover_context.prepare(user['id'],entity_id,body)
    return start_task(user['id'],'cover_letter',work,{'workspace_id':entity_id,'operation':'questions',**body.model_dump()})

@app.post('/api/cover-workspaces/{entity_id}/questions/skip')
def cover_skip_questions(entity_id:str,body:CoverQuestionSkip,user=Depends(auth.current)):
    return cover_context.skip(user['id'],entity_id,body)

@app.post('/api/cover-workspaces/{entity_id}/context/review')
async def cover_context_review(entity_id:str,body:CoverContextReview,user=Depends(auth.current)):
    require(user['id'],entity_id,'cover_workspace')
    if body.build:require_ai(user['id'])
    async def work():return await cover_context.review(user['id'],entity_id,body)
    return start_task(user['id'],'cover_letter',work,{'workspace_id':entity_id,'operation':'context/review',**body.model_dump()})

@app.post('/api/cover-workspaces/{entity_id}/message')
async def cover_message(entity_id:str,body:CoverMessage,user=Depends(auth.current)):
    require_ai(user['id']);require(user['id'],entity_id,'cover_workspace')
    async def work():return await cover_letters.send(user['id'],entity_id,body)
    return start_task(user['id'],'cover_letter',work,{'workspace_id':entity_id,'operation':'message',**body.model_dump()})

@app.post('/api/cover-workspaces/{entity_id}/render')
async def cover_render(entity_id:str,body:CoverEdit,user=Depends(auth.current)):
    require(user['id'],entity_id,'cover_workspace')
    async def work():return await cover_letters.render(user['id'],entity_id,body)
    return start_task(user['id'],'cover_letter',work,{'workspace_id':entity_id,'operation':'render',**body.model_dump()})

@app.post('/api/cover-workspaces/{entity_id}/restore')
def cover_restore(entity_id:str,body:RevisionAction,user=Depends(auth.current)):
    return cover_letters.restore(user['id'],entity_id,body)

@app.post('/api/cover-workspaces/{entity_id}/finalize')
def cover_finalize(entity_id:str,body:FinalizeRevision,user=Depends(auth.current)):
    return cover_letters.finalize(user['id'],entity_id,body)

@app.get('/api/cover-revisions/{entity_id}/pages/{page}')
def cover_preview(entity_id:str,page:int,user=Depends(auth.current)):
    data=require(user['id'],entity_id,'cover_revision')['data']
    if page<1 or page>data['layout']['pages']:raise HTTPException(404,'Page not found.')
    return Response(documents.pdf_preview(base64.b64decode(data['artifacts']['pdf']),page),media_type='image/png')

@app.get('/api/cover-letters/{entity_id}/export/{format}')
def cover_export(entity_id:str,format:Literal['pdf','docx','txt'],user=Depends(auth.current)):
    data=require(user['id'],entity_id,'cover_letter')['data']
    if data['layout']['pages']!=1 or not data['layout']['validated']:raise HTTPException(409,'Save a validated one-page letter before downloading.')
    raw,mime=cover_letters.export_data(data,format);filename=cover_letters.filename(data,format)
    fallback=re.sub(r'[^a-zA-Z0-9 ._-]','_',filename)
    return Response(raw,media_type=mime,headers={'Content-Disposition':f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename,safe='')}"})

@app.get('/api/applications')
def list_applications(user=Depends(auth.current)):
    applications.migrate(user['id'])
    return db.list_entities(user['id'],'application')

@app.get('/api/applications/dashboard')
def application_dashboard(start:str='',end:str='',period:Literal['week','month']='week',timezone_name:str='UTC',include_archived:bool=False,user=Depends(auth.current)):
    for value in (start,end):
        try: ApplicationEvent.valid_date(value)
        except ValueError: raise HTTPException(422,'Use YYYY-MM-DD date filters.') from None
    if start and end and start>end: raise HTTPException(422,'Start must be before end.')
    if start and end:
        from datetime import date
        if (date.fromisoformat(end)-date.fromisoformat(start)).days>365:raise HTTPException(422,'Choose a chart range of up to one year (366 days).')
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    try:ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError,ValueError):raise HTTPException(422,'Choose a valid chart time zone.') from None
    applications.migrate(user['id'])
    return applications.dashboard(db.list_entities(user['id'],'application'),start,end,period,timezone_name,include_archived)

@app.post('/api/applications')
def add_application(body:ApplicationInput,user=Depends(auth.current)):
    data=body.model_dump();applications.validate_links(user['id'],data)
    with applications.LOCK:
        if body.job_id and any(r['data'].get('job_id')==body.job_id for r in db.list_entities(user['id'],'application')): raise HTTPException(409,'This posting is already in Applications.')
        if body.job_id: data['posting_snapshot']=dict(require(user['id'],body.job_id,'job')['data'])
        else: data['posting_snapshot']={**data['posting_snapshot'],'title':body.title,'company':body.company,'url':body.url}
        if data['status']!='preparing' and not data['history']: data['history']=[{'status':data['status'],'date':data['applied_date'] if data['status']=='applied' else '', 'note':''}]
        return db.save(user['id'],'application',data)

@app.get('/api/applications/{entity_id}')
def get_application(entity_id:str,user=Depends(auth.current)):
    return require(user['id'],entity_id,'application')

@app.put('/api/applications/{entity_id}')
def edit_application(entity_id:str,body:ApplicationInput,expected_updated_at:str=Query(''),user=Depends(auth.current)):
    with applications.LOCK:
        old=require(user['id'],entity_id,'application')
        if expected_updated_at and expected_updated_at!=old['updated_at']:raise HTTPException(409,'This application changed in another window. Reload saved changes before saving again.')
        data=body.model_dump();applications.validate_links(user['id'],data)
        old_files={a['record_id'] for a in old['data'].get('attachments',[]) if a['kind']=='document'}
        new_files={a['record_id'] for a in data.get('attachments',[]) if a['kind']=='document'}
        if old_files!=new_files:raise HTTPException(409,'Application files changed. Reopen details; use document controls to remove files.')
        for rid in old['data'].get('resume_ids',[]):
            r=db.get(user['id'],rid,'resume')
            if r and r['data'].get('origin')=='uploaded' and rid not in data['resume_ids']:raise HTTPException(409,'Use the document controls to remove an uploaded resume.')
        if data['job_id']!=old['data'].get('job_id',''): raise HTTPException(409,'The linked posting cannot be replaced. Create a separate application.')
        data['posting_snapshot']=old['data'].get('posting_snapshot',{})
        if data['status']!=old['data']['status'] and (not data['history'] or data['history'][-1]['status']!=data['status']): data['history'].append({'status':data['status'],'date':data['applied_date'] if data['status']=='applied' else '', 'note':''})
        return db.save(user['id'],'application',data,entity_id)

@app.delete('/api/applications/{entity_id}')
def delete_application(entity_id:str,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'application')
    if any(a.get('kind')=='document' for a in record['data'].get('attachments',[])):raise HTTPException(409,'Remove uploaded files first, or archive this application to preserve its documents.')
    require(user['id'],entity_id,'application');db.delete(user['id'],entity_id)
    return {'ok':True}

@app.get('/api/guidance')
def writing_guidance(user=Depends(auth.current)):
    return guidance.catalog()

@app.get('/api/resources')
def resources(user=Depends(auth.current)):
    return json.loads((config.CONTENT_DIR/'resources.json').read_text())

@app.post('/api/preparation')
async def preparation(body:PrepRequest,user=Depends(auth.current)):
    require_ai(user['id']);job=require(user['id'],body.job_id,'job')
    if body.analysis_id: require(user['id'],body.analysis_id,'analysis')
    async def work(): return db.save(user['id'],'prep',{**(await ai.prepare(user['id'],job['data'],body.confirmed_gaps,body.mode)),'job_id':body.job_id,'analysis_id':body.analysis_id})
    return start_task(user['id'],'preparation',work)

@app.post('/api/interviews')
async def interview_answer(body:AnswerRequest,user=Depends(auth.current)):
    require_ai(user['id']);job=require(user['id'],body.job_id,'job')
    session=require(user['id'],body.session_id,'interview') if body.session_id else None
    if session and (session['data']['job_id']!=body.job_id or session['data']['question']!=body.question):
        raise HTTPException(409,'Start a new interview session for a different role or question.')
    async def work():
        feedback=await ai.interview(user['id'],job['data'],body.question,body.answer,body.mode)
        previous=session['data'].get('attempts',[]) if session else []
        return db.save(user['id'],'interview',{'job_id':body.job_id,'question':body.question,'attempts':previous+[{'answer':body.answer,'feedback':feedback,'at':db.now()}]},session['id'] if session else None)
    return start_task(user['id'],'interview',work)

@app.get('/api/assessment/questions')
async def questions(user=Depends(auth.current)): return await integrations.onet_questions()

@app.put('/api/assessment/progress')
def progress(body:AssessmentProgress,user=Depends(auth.current)):
    if any(not k.isdigit() or not 1<=int(k)<=30 or type(v)!=int or not 1<=v<=5 for k,v in body.answers.items()): raise HTTPException(422,'Assessment responses must use question indices 1–30 and response values 1–5.')
    records=db.list_entities(user['id'],'assessment_progress')
    return db.save(user['id'],'assessment_progress',body.model_dump(),records[0]['id'] if records else None)

@app.post('/api/assessment/score')
async def score(body:AssessmentProgress,user=Depends(auth.current)):
    progress(body,user)
    if not config.ONET_KEY: raise HTTPException(503,'Configure ONET_API_KEY on the server to score the official questionnaire.')
    async def work(): return db.save(user['id'],'assessment',await integrations.onet_results(body.answers,body.job_zone))
    return start_task(user['id'],'assessment',work)

@app.post('/api/boards')
def add_board(body:Board,user=Depends(auth.current)):
    if len(db.list_entities(user['id'],'board'))>=16: raise HTTPException(400,'Keep the registry to at most 16 employer boards for this local version.')
    return db.save(user['id'],'board',body.model_dump())

@app.post('/api/jobs/search')
async def search(body:SearchRequest,user=Depends(auth.current)):
    if not body.sources: raise HTTPException(400,'Choose at least one source.')
    cache_key=json.dumps({'query':body.model_dump(exclude={'refresh'}),'ai_configuration':ai_settings.resolve(db.settings(user['id']),body.mode),'boards':[(b['id'],b['updated_at']) for b in db.list_entities(user['id'],'board')]},sort_keys=True)
    if not body.refresh:
        for cached in db.list_entities(user['id'],'search'):
            stamp=integrations.parse_date(cached['created_at'])
            if cached['data'].get('cache_key')==cache_key and stamp and (integrations.datetime.now(integrations.timezone.utc)-stamp).total_seconds()<86400:
                return {'cached':True,'result':cached}
    async def work(): return db.save(user['id'],'search',{**(await integrations.discover(user['id'],body)),'cache_key':cache_key})
    return start_task(user['id'],'discovery',work)

@app.post('/api/jobs/{entity_id}/check')
async def check_job(entity_id:str,user=Depends(auth.current)):
    record=require(user['id'],entity_id,'job');data=record['data']
    if not data.get('url'): raise ServiceError('This posting has no public URL to check.')
    result=await public_fetch(data['url'],2*1024*1024)
    status=result['status'];stamp=db.now()
    observation=f'Application page returned HTTP {status} at {stamp}.'
    if status in (404,410): observation+=' Listing appears unavailable.'
    elif status==200: observation+=' Page accessibility does not establish hiring intent.'
    return db.save(user['id'],'job',{**data,'last_checked_at':stamp,'application_http_status':status,'observations':data.get('observations',[])+[observation]},entity_id)

@app.post('/api/demo/{scenario}')
def demo(scenario:str,user=Depends(auth.current)):
    examples=json.loads((config.CONTENT_DIR/'examples.json').read_text())
    if scenario not in examples: raise HTTPException(404,'Example not found.')
    if db.list_entities(user['id'],'experience'): raise HTTPException(409,'Use an empty account for fictional examples so they do not mix with your own experience.')
    example=examples[scenario]
    db.update_settings(user['id'],example.get('profile',{'name':example['name'],'contact':example['contact']}))
    for item in example['experience']: db.save(user['id'],'experience',ExperienceItem.model_validate(item).model_dump())
    job=db.save(user['id'],'job',{'title':example['role'],'company':'Fictional classroom example','description':example['posting'],'url':''})
    return {'job':job,'message':'Fictional example loaded. This account now contains sample experience, not your real history.'}

BACKUP_KINDS={'usage_event','onboarding','project_source','project_snapshot','project_analysis','answer_draft','work_style','story_prompts','profile_answer','cover_workspace','cover_revision','cover_letter','resume_conversation','resume_revision','resume_draft','experience','document','job','analysis','resume','prep','interview','assessment','assessment_progress','board','search','application'}

@app.get('/api/account/export')
def backup(user=Depends(auth.current)):
    onboarding.status(user['id'])
    cost_history.recover(user['id'])
    applications.migrate(user['id']);profile_answers.migrate(user['id'])
    records=[r for kind in BACKUP_KINDS for r in db.list_entities(user['id'],kind)]
    files={}
    for record in records:
        if record['kind']=='document':
            path=config.DATA_DIR/'uploads'/user['id']/record['id']
            if path.exists(): files[record['id']]=base64.b64encode(path.read_bytes()).decode()
    profile=db.settings(user['id'])
    payload={'schema_version':1,'exported_at':db.now(),'profile':{k:profile[k] for k in SettingsUpdate.model_fields if k in profile},'records':[{k:r[k] for k in ('id','kind','data','created_at')} for r in records],'files':files}
    return Response(json.dumps(payload,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="career-companion-account-backup.json"'})

@app.post('/api/account/import')
async def restore(file:UploadFile=File(...),user=Depends(auth.current)):
    onboarding.status(user['id'])
    raw=await file.read(50*1024*1024+1)
    if len(raw)>50*1024*1024: raise ServiceError('The backup exceeds 50 MB.')
    try:
        payload=json.loads(raw)
        if not isinstance(payload,dict) or payload.get('schema_version')!=1 or not isinstance(payload.get('records'),list) or len(payload['records'])>23000: raise ValueError()
        records=payload['records']
        usage_count=sum(r.get('kind')=='usage_event' for r in records)
        if usage_count>20000 or len(records)-usage_count>3000:raise ValueError()
        by_id={r['id']:r for r in records};ids={r['id']:db.uid() for r in records};kinds={r['id']:r['kind'] for r in records}
        if len(ids)!=len(records): raise ValueError()
        decoded={}
        setup_records=[r for r in records if r.get('kind')=='onboarding']
        if len(setup_records)>1:raise ValueError()
        for record in records:
            if record['kind'] not in BACKUP_KINDS or not isinstance(record['data'],dict): raise ValueError()
            if record['kind']=='onboarding':onboarding.validate_backup(record['data'])
            if record['kind']=='usage_event':cost_history.UsageEvent.model_validate(record['data'])
            project_routes.validate_nested_references(record['data'],kinds,by_id)
            application_documents.validate_backup(record,kinds,by_id,payload.get('files',{}))
            if record['kind']=='experience':
                ExperienceItem.model_validate(record['data'])
                for credential in record['data'].get('certification_items',[]):
                    attachment=credential.get('document_id')
                    if attachment and (kinds.get(attachment)!='document' or by_id[attachment]['data'].get('purpose')!='certificate' or attachment not in payload.get('files',{})): raise ValueError()
            if record['kind']=='board': Board.model_validate(record['data'])
            if record['kind']=='profile_answer':
                data=record['data']
                if data['answer_kind'] not in ('experience','motivation') or data['status'] not in ('confirmed','archived') or not isinstance(data['version'],int) or data['version']<1:raise ValueError()
                if data.get('experience_id') and kinds.get(data['experience_id'])!='experience':raise ValueError()
                if data.get('scope',{}).get('job_id') and kinds.get(data['scope']['job_id'])!='job':raise ValueError()
                for source in data['sources']:
                    if source.get('builder')=='application_agent':
                        if kinds.get(source.get('application_id'))!='application' or (source.get('job_id') and kinds.get(source['job_id'])!='job'):raise ValueError()
                        if any(not isinstance(q.get('text'),str) or len(q['text'])>500 for q in source.get('questions',[])):raise ValueError()
                        continue
                    if source.get('builder') in ('project','work_style'):
                        if kinds.get(source.get('draft_id'))!='answer_draft':raise ValueError()
                        if source.get('snapshot_id') and kinds.get(source['snapshot_id'])!='project_snapshot':raise ValueError()
                        continue
                    if kinds.get(source['conversation_id'])!=('cover_workspace' if source['builder']=='cover' else 'resume_conversation'):raise ValueError()
                    if kinds.get(source['job_id'])!='job':raise ValueError()
                    if source.get('resume_id') and kinds.get(source['resume_id'])!='resume':raise ValueError()
                    context=by_id[source['conversation_id']]['data']
                    if source['job_id']!=context['job_id'] or (source.get('resume_id') and source['resume_id']!=context.get('resume_id')):raise ValueError()

            if record['kind'] in ('project_source','project_snapshot','project_analysis','answer_draft','work_style','story_prompts'):
                project_routes.validate_backup(record,kinds,by_id)
            if record['kind']=='resume_conversation':
                data=record['data']
                if kinds.get(data['job_id'])!='job' or not isinstance(data['version'],int) or not isinstance(data['messages'],list) or not isinstance(data['proposals'],list):raise ValueError()
                if data.get('analysis_id') and kinds.get(data['analysis_id'])!='analysis':raise ValueError()
                if any(kinds.get(i)!='resume_revision' for i in data['revision_ids']):raise ValueError()
                if data.get('current_revision_id') and data['current_revision_id'] not in data['revision_ids']:raise ValueError()
                for proposal in data['proposals']:
                    if proposal.get('record_id') and kinds.get(proposal['record_id'])!='experience':raise ValueError()
                    if proposal.get('applied_record_id') and kinds.get(proposal['applied_record_id'])!='experience':raise ValueError()
            if record['kind']=='resume_revision':
                data=record['data']
                if kinds.get(data['conversation_id'])!='resume_conversation' or kinds.get(data['job_id'])!='job':raise ValueError()
                if data['snapshot']['job_id']!=data['job_id']:raise ValueError()
                if any(kinds.get(row['id']) not in ('experience','profile_answer') for row in data['catalog']):raise ValueError()
                if data.get('finalized_resume_id') and kinds.get(data['finalized_resume_id'])!='resume':raise ValueError()
            if record['kind'] in ('cover_workspace','cover_revision','cover_letter'):
                data=record['data'];CoverContent.model_validate(data['content'])
                if kinds.get(data['job_id'])!='job' or kinds.get(data['resume_id'])!='resume':raise ValueError()
                if record['kind']=='cover_workspace':
                    if any(kinds.get(i)!='cover_revision' for i in data['revision_ids']):raise ValueError()
                    if data.get('current_revision_id') and data['current_revision_id'] not in data['revision_ids']:raise ValueError()
                    messages={m['id']:m for m in data.get('messages',[])}
                    questions={q['id']:q for q in data.get('questions',[])}
                    proposals={p['id']:p for p in data.get('context_proposals',[])}
                    if len(messages)!=len(data.get('messages',[])) or len(questions)!=len(data.get('questions',[])) or len(proposals)!=len(data.get('context_proposals',[])):raise ValueError()
                    for proposal in proposals.values():
                        if proposal['source_message_id'] not in messages or messages[proposal['source_message_id']]['role']!='user':raise ValueError()
                        if set(proposal.get('question_ids',[]))-questions.keys():raise ValueError()
                        if proposal.get('supersedes_id') and proposal['supersedes_id'] not in proposals:raise ValueError()
                        for field in ('profile_record_id','applied_record_id'):
                            if proposal.get(field) and kinds.get(proposal[field])!='experience':raise ValueError()
                else:
                    if kinds.get(data['workspace_id'])!='cover_workspace':raise ValueError()
                    if data.get('finalized_letter_id') and kinds.get(data['finalized_letter_id'])!='cover_letter':raise ValueError()
            if record['kind']=='application':
                application=ApplicationInput.model_validate(record['data'])
                kinds={r['id']:r['kind'] for r in records}
                if any(kinds.get(i)!='resume' for i in application.resume_ids): raise ValueError()
                if application.job_id and kinds.get(application.job_id)!='job': raise ValueError()
                if application.submitted_resume_id and application.submitted_resume_id not in application.resume_ids: raise ValueError()
                for attachment in application.attachments:
                    if kinds.get(attachment.record_id)!=attachment.kind:raise ValueError()
                    if attachment.kind=='document' and by_id[attachment.record_id]['data'].get('application_id')!=record['id']:raise ValueError()
                if application.workflow:
                    flow=ApplicationWorkflow.model_validate(application.workflow)
                    if flow.resume_id and flow.resume_id not in application.resume_ids:raise ValueError()
                    if flow.cover_letter_id and (kinds.get(flow.cover_letter_id)!='cover_letter' or not any(a.record_id==flow.cover_letter_id for a in application.attachments)):raise ValueError()
                    if flow.step!='resume' and not flow.resume_id:raise ValueError()
                    if flow.step=='agent' and not (flow.cover_skipped or flow.cover_letter_id):raise ValueError()
                    if flow.cover_letter_id and (by_id[flow.cover_letter_id]['data']['resume_id']!=flow.resume_id or by_id[flow.cover_letter_id]['data']['job_id']!=application.job_id):raise ValueError()

        for old,content in payload.get('files',{}).items():
            if old not in ids or not any(r['id']==old and r['kind']=='document' for r in records): raise ValueError()
            decoded[ids[old]]=base64.b64decode(content,validate=True)
            if len(decoded[ids[old]])>config.MAX_UPLOAD: raise ValueError()
            if by_id[old]['data'].get('purpose')=='application':
                checked=application_documents.inspect(by_id[old]['data']['filename'],decoded[ids[old]])
                if checked['sha256']!=by_id[old]['data'].get('sha256'):raise ValueError()
            if by_id[old]['data'].get('purpose')=='certificate':
                certifications.inspect_file(by_id[old]['data']['filename'],decoded[ids[old]])
        profile=SettingsUpdate.model_validate(payload.get('profile',{})).model_dump(exclude_none=True)
        ai_settings.validate_custom({**db.settings(user['id']),**profile})
        if profile.get('contact') and 'contact_reviewed' not in profile: profile['contact_reviewed']=False
    except (ValueError,KeyError,TypeError,ValidationError): raise ServiceError('This is not a supported Career Companion account backup. Nothing was imported.') from None
    def remap(value):
        if isinstance(value,str): return 'library:'+ids[value[8:]] if value.startswith('library:') and value[8:] in ids else ids.get(value,value)
        if isinstance(value,list): return [remap(x) for x in value]
        if isinstance(value,dict): return {ids.get(k,k):remap(v) for k,v in value.items() if k not in ('password','token','csrf','api_key','path','user_id')}
        return value
    existing_usage={r['data']['event_key']:r['id'] for r in db.list_entities(user['id'],'usage_event')}
    for record in records:
        if record['kind']=='usage_event':ids[record['id']]=existing_usage.get(record['data']['event_key'],cost_history.digest([user['id'],record['data']['event_key']])[:32])
    # Import is additive; existing records are preserved and IDs are remapped.
    for record in records:
        if record['kind']=='usage_event':
            data={**record['data'],'task_id':''}
            if data['event_key'] not in existing_usage:
                saved=cost_history.write(user['id'],data);existing_usage[data['event_key']]=saved['id']
        elif record['kind']!='onboarding':db.save(user['id'],record['kind'],remap(record['data']),ids[record['id']])
    onboarding.restore(user['id'],setup_records[0]['data'] if setup_records else None,legacy=any(r['kind'] in onboarding.LEGACY for r in records))
    # Restored pending proposals use the new record timestamp only when their reviewed
    # original still matches. Conflicting/newer source data continues to block approval.
    for old in records:
        if old['kind']!='resume_conversation':continue
        conversation=db.get(user['id'],ids[old['id']],'resume_conversation');changed=False
        for proposal in conversation['data']['proposals']:
            if proposal.get('status')!='pending' or not proposal.get('record_id'):continue
            target=db.get(user['id'],proposal['record_id'],'experience')
            if target and target['data']==proposal.get('original'):
                proposal['expected_updated_at']=target['updated_at'];changed=True
        if changed:db.save(user['id'],'resume_conversation',conversation['data'],conversation['id'])
    for old in records:
        if old['kind']!='cover_workspace':continue
        workspace=db.get(user['id'],ids[old['id']],'cover_workspace');changed=False
        for proposal in workspace['data'].get('context_proposals',[]):
            if proposal.get('status')!='pending' or not proposal.get('profile_record_id'):continue
            target=db.get(user['id'],proposal['profile_record_id'],'experience')
            if target and target['data']==proposal.get('profile_original'):
                proposal['profile_expected_updated_at']=target['updated_at'];changed=True
        if changed:db.save(user['id'],'cover_workspace',workspace['data'],workspace['id'])
    folder=config.DATA_DIR/'uploads'/user['id'];folder.mkdir(parents=True,exist_ok=True)
    for name,content in decoded.items(): (folder/name).write_bytes(content)
    db.update_settings(user['id'],profile)
    return {'imported':len(records),'message':'Backup imported with new record IDs. Existing records were preserved.'}

class DeleteAccount(StrictModel):
    username:str
    password:str=Field(max_length=200)

@app.delete('/api/account')
def delete_account(body:DeleteAccount,response:Response,user=Depends(auth.current)):
    with db.connect() as c:
        row=c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()
        if body.username!=row['username'] or not auth.verify(row['password'],body.password): raise HTTPException(401,'Confirm your username and password to delete this local account.')
        for row_task in c.execute('SELECT id FROM tasks WHERE user_id=?',(user['id'],)).fetchall():
            task=workers.get(row_task['id'])
            if task: task.cancel()
        c.execute('DELETE FROM evidence_fts WHERE user_id=?',(user['id'],))
        c.execute('DELETE FROM users WHERE id=?',(user['id'],))
    shutil.rmtree(config.DATA_DIR/'uploads'/user['id'],ignore_errors=True)
    credentials.remove(user['id'])
    response.delete_cookie('next_step_session',path='/')
    return {'ok':True}

@app.get('/{path:path}')
def frontend(path:str):
    if path.startswith('api/'): raise HTTPException(404,'API route not found.')
    target=(config.STATIC_DIR/path).resolve()
    if target.is_relative_to(config.STATIC_DIR.resolve()) and target.is_file(): return FileResponse(target)
    index=config.STATIC_DIR/'index.html'
    if index.exists(): return FileResponse(index)
    return JSONResponse({'detail':'Frontend has not been built. Run the Docker build or the frontend build script.'},503)
