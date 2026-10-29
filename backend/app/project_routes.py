"""Authenticated interfaces for source snapshots, shared answer review and private reflection."""
import asyncio
import json
import re
from fastapi import Depends, UploadFile, File, Form, HTTPException
from pydantic import Field, StrictInt
from . import auth, db, project_uploads, project_sources as sources, work_style, answer_drafts
from .models import StrictModel
from .network import ServiceError

class SourceURL(StrictModel):
    url:str=Field(default='',max_length=2000)
    urls:list[str]=Field(default_factory=list,max_length=5)
class Selection(StrictModel):
    file_paths:list[str]=Field(min_length=1,max_length=30)
    experience_id:str=Field(default='',max_length=64)
class Combined(StrictModel):
    source_ids:list[str]=Field(min_length=1,max_length=5)
    urls:list[str]=Field(default_factory=list,max_length=5)
    experience_id:str=Field(default='',max_length=64)
class Pasted(StrictModel):
    title:str=Field(min_length=1,max_length=200)
    text:str=Field(min_length=1,max_length=200000)
    url:str=Field(default='',max_length=2000)
    experience_id:str=Field(default='',max_length=64)
class Analyze(StrictModel):
    mode:str=Field(default='economy',pattern='^(economy|deep|custom)$')
    request_token:str=Field(default='',max_length=100)
class Attach(StrictModel):
    builder:str=Field(pattern='^(resume|cover)$')
    conversation_id:str=Field(max_length=64)
    question_id:str=Field(default='',max_length=100)
    expected_version:int=Field(ge=0)
class Archive(StrictModel):
    archived:bool=True
class Progress(StrictModel):
    expected_version:int=Field(ge=1)
    answers:dict[str,StrictInt]=Field(max_length=120)
    comparison_answers:dict[str,str]|None=Field(default=None,max_length=12)
    page:int=Field(default=0,ge=0,le=16)
class Prompts(Analyze):
    themes:list[str]=Field(min_length=1,max_length=5)
    job_id:str=Field(default='',max_length=64)
class Draft(StrictModel):
    expected_version:int=Field(ge=0)
    title:str=Field(min_length=1,max_length=200)
    text:str=Field(default='',max_length=6000)
    contribution:str=Field(default='',max_length=3000)
    experience_id:str=Field(default='',max_length=64)
    question_answers:dict[str,str]=Field(default_factory=dict,max_length=3)
    question:str=Field(default='',max_length=2000)
    prompt_id:str=Field(default='',max_length=64)
class Review(StrictModel):
    expected_version:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=200)
    text:str=Field(default='',max_length=6000)
    contribution:str=Field(default='',max_length=3000)
    confirmed:bool=False
    rejected:bool=False
    experience_id:str=Field(default='',max_length=64)
    experience_updated_at:str=Field(default='',max_length=100)
    create_experience:bool=False
    update_experience:bool=False

def install(app,start_task,require_ai):
    @app.get('/api/project-sources')
    def listing(user=Depends(auth.current)):
        # Restore status after navigation/reload without starting another analysis.
        tasks=[];seen=set()
        with db.connect() as c:
            for row in c.execute("SELECT id,status,error,result,created_at,updated_at FROM tasks WHERE user_id=? AND kind='project_analysis' ORDER BY created_at DESC",(user['id'],)):
                saved=json.loads(row['result']) if row['result'] else {}
                inputs=saved.get('_task_inputs',saved.get('inputs',{})) or {}
                snapshot_id=inputs.get('snapshot_id')
                if snapshot_id and snapshot_id not in seen:
                    seen.add(snapshot_id)
                    tasks.append({**{key:row[key] for key in ('id','status','error','created_at','updated_at')},'snapshot_id':snapshot_id})
        return {'sources':db.list_entities(user['id'],'project_source'),'snapshots':db.list_entities(user['id'],'project_snapshot'),'analyses':db.list_entities(user['id'],'project_analysis'),'drafts':db.list_entities(user['id'],'answer_draft'),'tasks':tasks}
    @app.post('/api/project-sources/github')
    async def discover(body:SourceURL,user=Depends(auth.current)):
        return await sources.discover_links(user['id'],body.urls or [body.url])
    @app.post('/api/project-sources/{id}/refresh')
    async def refresh(id:str,user=Depends(auth.current)):
        old=sources.require(user['id'],id,'project_source')
        if old['data']['provider']!='github':raise HTTPException(400,'Upload or paste a new copy to refresh this source.')
        return await sources.discover_links(user['id'],old['data'].get('urls') or [old['data']['url']])
    @app.post('/api/project-sources/{id}/estimate')
    def selection_estimate(id:str,body:Selection,mode:str='economy',user=Depends(auth.current)):
        source=sources.require(user['id'],id,'project_source')
        available={f['file_path'] for f in source['data'].get('available_files',[])}
        if len(set(body.file_paths))!=len(body.file_paths) or set(body.file_paths)-available:raise HTTPException(400,'Choose files from this project.')
        # The exact text has not been downloaded yet; budget each selected file at the analysis cap.
        return {**sources.estimate(user['id'],mode,min(60000,len(body.file_paths)*12000)),'note':'Planning estimate for the selected files; actual extracted text and usage may be lower or higher.'}
    @app.post('/api/project-sources/{id}/select')
    async def select(id:str,body:Selection,user=Depends(auth.current)):
        return await sources.select(user['id'],id,body.file_paths,body.experience_id)
    @app.post('/api/project-sources/combine')
    def combine(body:Combined,user=Depends(auth.current)):
        return project_uploads.combine(user['id'],body.source_ids,body.urls,body.experience_id)
    @app.post('/api/project-sources/upload-preview')
    async def upload_preview(files:list[UploadFile]=File(...),experience_id:str=Form(default='',max_length=64),user=Depends(auth.current)):
        if experience_id:sources.require(user['id'],experience_id,'experience')
        if len(files)>30:raise HTTPException(400,'Choose at most 30 uploads.')
        uploads=[];total=0
        for f in files:
            raw=await f.read(project_uploads.MAX_UPLOAD+1);total+=len(raw)
            if total>project_uploads.MAX_UPLOAD:raise HTTPException(413,'This upload exceeds 32 MB.')
            uploads.append((f.filename or 'upload.txt',raw))
        return await asyncio.to_thread(project_uploads.preview,user['id'],uploads,experience_id)
    @app.post('/api/project-sources/paste')
    def paste(body:Pasted,user=Depends(auth.current)):
        from .models import validate_link
        try:validate_link(body.url)
        except ValueError:raise HTTPException(400,'Use a complete public http:// or https:// original link without credentials.') from None
        source=db.save(user['id'],'project_source',{'provider':'paste','label':body.title,'url':body.url,'archived':False,'version':1})
        return sources.snapshot(user['id'],source,[sources.extracted('Profile or project notes.txt',body.text.encode())],experience_id=body.experience_id)
    @app.post('/api/project-sources/upload')
    async def upload(files:list[UploadFile]=File(...),experience_id:str=Form(default='',max_length=64),user=Depends(auth.current)):
        if experience_id:sources.require(user['id'],experience_id,'experience')
        if len(files)>30:raise HTTPException(400,'Choose at most 30 files.')
        selected=[];excluded=[];paths=set();total=0
        for f in files:
            path=(f.filename or 'upload.txt').replace('\\','/');raw=await f.read(10*1024*1024+1);total+=len(raw)
            if total>32*1024*1024:raise HTTPException(413,'This upload exceeds 32 MB.')
            if not sources.allowed(path) or path in paths or len(raw)>10*1024*1024:
                excluded.append({'file_path':path,'reason':'Unsupported, duplicate, credential-like, generated, or larger than 10 MB'});continue
            paths.add(path)
            try:entry=await asyncio.to_thread(sources.extracted,path,raw)
            except ServiceError as e:excluded.append({'file_path':path,'reason':str(e)});continue
            if sum(len(x['text'].encode()) for x in selected)+len(entry['text'].encode())>sources.MAX_TOTAL:
                excluded.append({'file_path':path,'reason':'2 MB extracted text limit'});continue
            selected.append(entry)
        if not selected:raise HTTPException(400,'No readable files. Use text/code, notebooks, PDF, or DOCX; archives and binaries are excluded.')
        source=db.save(user['id'],'project_source',{'provider':'upload','label':selected[0]['file_path']+(' and other files' if len(selected)>1 else ''),'archived':False,'version':1})
        return sources.snapshot(user['id'],source,selected,excluded,experience_id)
    @app.get('/api/project-snapshots/{id}')
    def snapshot(id:str,user=Depends(auth.current)):return sources.require(user['id'],id,'project_snapshot')
    @app.get('/api/project-snapshots/{id}/estimate')
    def estimate(id:str,mode:str='economy',user=Depends(auth.current)):
        data=sources.require(user['id'],id,'project_snapshot')['data']
        return sources.estimate(user['id'],mode,sum(len(f['text']) for f in sources.passages(data)))
    @app.post('/api/project-snapshots/{id}/notes')
    def source_notes(id:str,user=Depends(auth.current)):
        snap=sources.require(user['id'],id,'project_snapshot')
        from . import profile_answers
        key=profile_answers.key(user['id'],'source-notes:'+id)
        existing=next((r for r in db.list_entities(user['id'],'answer_draft') if r['data'].get('snapshot_id')==id and r['data'].get('manual_source')),None) or db.get(user['id'],key,'answer_draft')
        if existing:return existing
        return db.save(user['id'],'answer_draft',{'version':1,'status':'draft','builder':'project','manual_source':True,'title':snap['data']['label'][:200],'text':'','contribution':'','experience_id':snap['data'].get('experience_id',''),'snapshot_id':id,'questions':[{'id':'0','text':'What did you personally contribute, and which files help you remember it?'},{'id':'1','text':'What methods, checks and outcomes can you confirm? Leave uncertain details out.'}],'question_answers':{},'findings':[],'history':[]},key)
    @app.post('/api/project-snapshots/{id}/analyze')
    async def analyze(id:str,body:Analyze,user=Depends(auth.current)):
        require_ai(user['id']);sources.require(user['id'],id,'project_snapshot')
        return start_task(user['id'],'project_analysis',lambda:sources.analyze(user['id'],id,body.mode),{'snapshot_id':id,**body.model_dump()})
    @app.put('/api/project-snapshots/{id}/archive')
    def archive(id:str,body:Archive,user=Depends(auth.current)):
        row=sources.require(user['id'],id,'project_snapshot')
        return db.save(user['id'],'project_snapshot',{**row['data'],'archived':body.archived},id)
    @app.post('/api/project-snapshots/{id}/attach')
    def attach(id:str,body:Attach,user=Depends(auth.current)):
        from . import onboarding
        onboarding.require_complete(user['id'])
        sources.require(user['id'],id,'project_snapshot')
        from . import question_answers, profile_answers
        module,_=question_answers.module(body.builder)
        def change(data,c):
            qs=profile_answers.stable_questions(data,body.builder)
            if body.question_id:
                q=next((q for q in qs if q['id']==body.question_id),None)
                if not q:raise HTTPException(400,'Choose a question from this conversation.')
                q['project_snapshot_ids']=list(dict.fromkeys(q.get('project_snapshot_ids',[])+[id]))[-5:]
                from .project_context import catalog,references
                materials=catalog(user['id'],{**data,'project_snapshot_ids':q['project_snapshot_ids']})
                attached=references([r['context_id'] for r in materials if r['snapshot_id'] in q['project_snapshot_ids']],materials)
                q['project_refs']=list({r['snapshot_id']:r for r in q.get('project_refs',[])+attached}.values())
                profile_answers.sync_questions(data,body.builder)
            data['project_snapshot_ids']=list(dict.fromkeys(data.get('project_snapshot_ids',[])+[id]))
            if len(data['project_snapshot_ids'])>5:raise HTTPException(400,'This conversation already has five sources. Use approved details in Profile or start a different source review.')
        module.mutate(user['id'],body.conversation_id,body.expected_version,change)
        return module.state(user['id'],body.conversation_id)
    @app.get('/api/answer-drafts')
    def drafts(user=Depends(auth.current)):return db.list_entities(user['id'],'answer_draft')
    @app.post('/api/answer-drafts')
    def new_draft(body:Draft,user=Depends(auth.current)):return answer_drafts.save(user['id'],None,body)
    @app.put('/api/answer-drafts/{id}')
    def save_draft(id:str,body:Draft,user=Depends(auth.current)):return answer_drafts.save(user['id'],id,body)
    @app.post('/api/profile-answers/drafts/{id}/review')
    def review_draft(id:str,body:Review,user=Depends(auth.current)):return answer_drafts.review(user['id'],id,body)
    @app.get('/api/work-style/catalog')
    def catalog(user=Depends(auth.current)):return work_style.catalog()
    @app.get('/api/work-style')
    def attempts(user=Depends(auth.current)):return db.list_entities(user['id'],'work_style')
    @app.post('/api/work-style')
    def start(user=Depends(auth.current)):return work_style.start(user['id'])
    @app.put('/api/work-style/{id}/progress')
    def progress(id:str,body:Progress,user=Depends(auth.current)):return work_style.mutate(user['id'],id,body.expected_version,body.answers,body.page,comparisons=body.comparison_answers)
    @app.post('/api/work-style/{id}/score')
    def score(id:str,body:Progress,user=Depends(auth.current)):return work_style.mutate(user['id'],id,body.expected_version,body.answers,body.page,True,body.comparison_answers)
    @app.get('/api/work-style/prompt-estimate')
    def prompt_estimate(mode:str='economy',user=Depends(auth.current)):return sources.estimate(user['id'],mode,8000,800)
    @app.post('/api/work-style/prompts')
    async def prompts(body:Prompts,user=Depends(auth.current)):
        if body.job_id:
            from . import onboarding
            onboarding.require_complete(user['id'])
        require_ai(user['id'])
        return start_task(user['id'],'story_prompts',lambda:work_style.prompts(user['id'],body),body.model_dump())
    @app.get('/api/work-style/prompts')
    def saved_prompts(user=Depends(auth.current)):return db.list_entities(user['id'],'story_prompts')

def validate_backup(record,kinds,by_id):
    """Validate references before additive restore writes any new records."""
    data=record['data'];kind=record['kind']
    refs={'source_id':'project_source','snapshot_id':'project_snapshot','analysis_id':'project_analysis','experience_id':'experience','profile_answer_id':'profile_answer','prompt_id':'story_prompts','job_id':'job'}
    for key,target in refs.items():
        if data.get(key) and kinds.get(data[key])!=target:raise ValueError('Invalid project/reflection reference')
    if kind=='project_source' and data.get('provider') in ('upload_preview','mixed'):
        files=data.get('available_files',[])
        if not 1<=len(files)<=3000:raise ValueError()
        if any(not sources.allowed(f['file_path']) or len(f['file_path'])>500 or ('text' in f and (not isinstance(f['text'],str) or len(f['text'].encode())>sources.MAX_FILE)) for f in files):raise ValueError()
        if sum(len(f.get('text','').encode()) for f in files)>sources.MAX_TOTAL:raise ValueError()
        try:project_uploads.links(data.get('urls',[]))
        except HTTPException:raise ValueError() from None
    if kind=='project_snapshot':
        if not data.get('source_id') or not 1<=len(data['files'])<=30:raise ValueError()
        if any(not sources.allowed(f['file_path']) or not isinstance(f['text'],str) or len(f['text'].encode())>sources.MAX_FILE for f in data['files']):raise ValueError()
        if sum(len(f['text'].encode()) for f in data['files'])>sources.MAX_TOTAL:raise ValueError()
    if kind=='answer_draft':
        Draft(expected_version=data['version'],title=data['title'],text=data.get('text',''),contribution=data.get('contribution',''),question_answers=data.get('question_answers',{}))
        if data['status'] not in ('draft','rejected','reviewed') or data['builder'] not in ('project','work_style'):raise ValueError()
        if data['builder']=='project':
            if not data.get('snapshot_id') or (not data.get('analysis_id') and not data.get('manual_source')):raise ValueError()
            if data.get('analysis_id') and by_id[data['analysis_id']]['data']['snapshot_id']!=data['snapshot_id']:raise ValueError()
    if kind=='work_style':
        work_style.validate_backup(data)

def validate_nested_references(value,kinds,by_id=None):
    if isinstance(value,list):
        for item in value:validate_nested_references(item,kinds,by_id)
    elif isinstance(value,dict):
        for key,item in value.items():
            if key=='project_snapshot_ids' and (not isinstance(item,list) or any(kinds.get(id)!='project_snapshot' for id in item)):raise ValueError()
            if key=='project_context_ids' and (not isinstance(item,list) or any(kinds.get(id) not in ('project_snapshot','project_analysis') for id in item)):raise ValueError()
            if key=='experience_ids' and ('answer_kind' in value or value.get('kind') in ('experience','motivation')) and (not isinstance(item,list) or len(item)>10 or len(set(item))!=len(item) or any(not isinstance(id,str) or kinds.get(id)!='experience' for id in item)):raise ValueError()
            if key=='evidence_experience_id' and item and kinds.get(item)!='experience':raise ValueError()
            if key=='project_refs':
                if not isinstance(item,list):raise ValueError()
                for ref in item:
                    if not isinstance(ref,dict) or kinds.get(ref.get('snapshot_id'))!='project_snapshot':raise ValueError()
                    if ref.get('experience_id') and kinds.get(ref['experience_id'])!='experience':raise ValueError()
                    if ref.get('analysis_id') and kinds.get(ref['analysis_id'])!='project_analysis':raise ValueError()
                    if by_id:
                        if ref.get('analysis_id') and by_id[ref['analysis_id']]['data']['snapshot_id']!=ref['snapshot_id']:raise ValueError()
                        files={f['file_path']:f['text'] for f in by_id[ref['snapshot_id']]['data']['files']}
                        if any(not f.get('quote') or f.get('file_path') not in files or f['quote'] not in files[f['file_path']] for f in ref.get('findings',[])):raise ValueError()
            validate_nested_references(item,kinds,by_id)
