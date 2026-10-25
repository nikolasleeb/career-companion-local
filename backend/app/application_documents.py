"""Original application files, isolated from Profile ingestion and generated layouts."""
import copy
import hashlib
import io
import json
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import Field
from pypdf import PdfReader
from . import storage
from . import auth, applications, config, db, documents
from .models import StrictModel
from .network import ServiceError

router=APIRouter(prefix='/api')
Category=Literal['resume','cover_letter','interview_prep','email','other']
MIMES={'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.txt':'text/plain; charset=utf-8'}

def owned(user,id,kind):
    record=db.get(user,id,kind)
    if not record:raise HTTPException(404,'Application document not found.')
    return record

def inspect(filename,raw):
    suffix=Path(filename).suffix.lower()
    if suffix not in MIMES:raise ServiceError('Choose a PDF, DOCX, or UTF-8 TXT file.')
    if not raw or len(raw)>10*1024*1024:raise ServiceError('Choose a nonempty file of 10 MB or less.')
    if suffix=='.pdf':
        try:
            if not raw.startswith(b'%PDF-'):raise ValueError()
            pdf=PdfReader(io.BytesIO(raw))
            if pdf.is_encrypted:raise ServiceError('Upload an unlocked PDF.')
            if not 1<=len(pdf.pages)<=30:raise ServiceError('Choose a PDF with 1 to 30 pages.')
            pages=len(pdf.pages)
        except ServiceError:raise
        except Exception:raise ServiceError('This PDF could not be read. Export a new PDF and try again.') from None
    else:
        # Reuse archive, embedded-object, expansion and external-resource checks.
        value=documents.extract(filename,raw);pages=value['pages']
    return {'mime':MIMES[suffix],'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'pages':pages}

def raw_file(user,document):
    path=config.DATA_DIR/'uploads'/user/document['id']
    if not path.is_file():raise HTTPException(409,'The original file is unavailable. Restore it from a backup or upload it again.')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=document['data']['sha256']:raise HTTPException(409,'The original file changed. Restore it from a backup before using it.')
    return raw

def linked(user,application_id,document_id):
    application=owned(user,application_id,'application');document=owned(user,document_id,'document')
    if document['data'].get('purpose')!='application' or document['data'].get('application_id')!=application_id or not any(a['record_id']==document_id and a['kind']=='document' for a in application['data'].get('attachments',[])):
        raise HTTPException(404,'Application document not found.')
    return application,document

def uploaded_original(user,resume):
    document=owned(user,resume['data']['document_id'],'document')
    if document['data'].get('purpose')!='application' or document['data'].get('resume_id')!=resume['id']:raise HTTPException(409,'This uploaded resume reference is invalid.')
    return document,raw_file(user,document)

def response_file(raw,filename,mime,inline=False):
    from urllib.parse import quote
    fallback='document'+Path(filename).suffix.lower()
    return Response(raw,media_type=mime,headers={'Content-Disposition':f'{"inline" if inline else "attachment"}; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename,safe="")}'})

@router.post('/applications/{application_id}/documents')
async def upload(application_id:str,file:UploadFile=File(...),category:Category=Form('other'),request_token:str=Form(min_length=8,max_length=100),user=Depends(auth.current)):
    raw=await file.read(10*1024*1024+1);filename=Path((file.filename or 'document.txt').replace('\\','/')).name[:200]
    metadata=inspect(filename,raw);uid=user['id']
    identity=hashlib.sha256((uid+'\0attachment\0'+application_id+'\0'+request_token).encode()).hexdigest()[:32]
    with applications.LOCK,db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        app=owned(uid,application_id,'application')
        existing=db.get(uid,identity,'document')
        if existing:
            if existing['data']['sha256']!=metadata['sha256'] or existing['data']['category']!=category:raise HTTPException(409,'This upload request was already used for a different file.')
            linked(uid,application_id,identity)
            return {'application':app,'document':existing,'resume':db.get(uid,existing['data'].get('resume_id',''),'resume')}
        if len(app['data'].get('attachments',[]))>=100:raise ServiceError('This application already has 100 attachments.')
        resume_id=db.uid() if category=='resume' else ''
        data={**metadata,'filename':filename,'display_name':filename,'purpose':'application','category':category,'application_id':application_id,'resume_id':resume_id,'text':'','reviewed':False}
        from .resume_conversation import write
        write(c,uid,'document',data,identity)
        if resume_id:
            if len(app['data'].get('resume_ids',[]))>=100:raise ServiceError('This application already has 100 resume versions.')
            job=db.get(uid,app['data'].get('job_id',''),'job')
            value={'origin':'uploaded','document_id':identity,'job_id':app['data'].get('job_id',''),'posting_snapshot':copy.deepcopy(app['data'].get('posting_snapshot') or (job or {}).get('data',{})),'title':filename,'name':'','headline':'','contact_lines':[],'sections':[],'source_text':'','source_reviewed':False}
            write(c,uid,'resume',value,resume_id)
            app['data']['resume_ids']=list(dict.fromkeys(app['data'].get('resume_ids',[])+[resume_id]))
            app['data']['workflow']={'step':'resume','resume_id':resume_id,'cover_letter_id':'','cover_skipped':False}
        app['data']['attachments']=app['data'].get('attachments',[])+[{'kind':'document','record_id':identity}]
        folder=config.DATA_DIR/'uploads'/uid;folder.mkdir(parents=True,exist_ok=True)
        path=folder/identity
        try:
            storage.write_bytes(path,raw);write(c,uid,'application',app['data'],app['id'])
        except BaseException:
            path.unlink(missing_ok=True);raise
    return {'application':owned(uid,application_id,'application'),'document':owned(uid,identity,'document'),'resume':db.get(uid,resume_id,'resume') if resume_id else None}

@router.get('/applications/{application_id}/documents/{document_id}/download')
def download(application_id:str,document_id:str,user=Depends(auth.current)):
    _,document=linked(user['id'],application_id,document_id)
    return response_file(raw_file(user['id'],document),document['data']['filename'],document['data']['mime'])

class Rename(StrictModel):
    display_name:str=Field(min_length=1,max_length=200)

@router.put('/applications/{application_id}/documents/{document_id}')
def rename(application_id:str,document_id:str,body:Rename,user=Depends(auth.current)):
    with applications.LOCK:
        _,document=linked(user['id'],application_id,document_id)
        return db.save(user['id'],'document',{**document['data'],'display_name':body.display_name},document_id)

class Promote(StrictModel):
    expected_updated_at:str

@router.post('/applications/{application_id}/documents/{document_id}/use-as-resume')
def promote_resume(application_id:str,document_id:str,body:Promote,user=Depends(auth.current)):
    """Promote a stored file atomically; retries cannot create another version."""
    uid=user['id']
    with applications.LOCK,db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        app,document=linked(uid,application_id,document_id);data=document['data']
        if data.get('resume_id'):
            resume=owned(uid,data['resume_id'],'resume')
            if data.get('category')!='resume' or resume['id'] not in app['data'].get('resume_ids',[]):raise HTTPException(409,'This document reference needs review before it can be used.')
            return {'application':app,'document':document,'resume':resume}
        if document['updated_at']!=body.expected_updated_at:raise HTTPException(409,'This file changed. Refresh its details before using it as a resume.')
        raw_file(uid,document)
        if len(app['data'].get('resume_ids',[]))>=100:raise ServiceError('This application already has 100 resume versions.')
        from .resume_conversation import write
        resume_id=db.uid();job=db.get(uid,app['data'].get('job_id',''),'job')
        value={'origin':'uploaded','document_id':document_id,'job_id':app['data'].get('job_id',''),'posting_snapshot':copy.deepcopy(app['data'].get('posting_snapshot') or (job or {}).get('data',{})),'title':data['display_name'],'name':'','headline':'','contact_lines':[],'sections':[],'source_text':'','source_reviewed':False}
        write(c,uid,'resume',value,resume_id)
        write(c,uid,'document',{**data,'category':'resume','resume_id':resume_id},document_id)
        updated=copy.deepcopy(app['data']);updated['resume_ids']=list(dict.fromkeys(updated.get('resume_ids',[])+[resume_id]))
        updated['workflow']={'step':'resume','resume_id':resume_id,'cover_letter_id':'','cover_skipped':False}
        write(c,uid,'application',updated,application_id)
    return {'application':owned(uid,application_id,'application'),'document':owned(uid,document_id,'document'),'resume':owned(uid,resume_id,'resume')}

@router.get('/applications/{application_id}/documents/{document_id}/text')
def extracted_text(application_id:str,document_id:str,user=Depends(auth.current)):
    _,document=linked(user['id'],application_id,document_id)
    if document['data']['category']!='resume':raise HTTPException(400,'Supporting documents are stored only and are not extracted for AI.')
    resume=owned(user['id'],document['data']['resume_id'],'resume')
    if resume['data'].get('source_reviewed'):return {'text':resume['data']['source_text'],'reviewed':True,'resume_updated_at':resume['updated_at'],'error':''}
    try:
        value=documents.extract(document['data']['filename'],raw_file(user['id'],document));text=value['text'];error=''
    except ServiceError as exc:text='';error=str(exc)
    return {'text':text,'reviewed':False,'resume_updated_at':resume['updated_at'],'error':error}

class Review(StrictModel):
    text:str=Field(min_length=30,max_length=100000)
    expected_updated_at:str

@router.put('/applications/{application_id}/documents/{document_id}/review')
def review(application_id:str,document_id:str,body:Review,user=Depends(auth.current)):
    with applications.LOCK:
        _,document=linked(user['id'],application_id,document_id)
        if document['data']['category']!='resume':raise HTTPException(400,'Only resume text can be reviewed here.')
        resume=owned(user['id'],document['data']['resume_id'],'resume')
        if resume['data'].get('source_reviewed'):
            if resume['data'].get('source_text')==body.text:return resume
            raise HTTPException(409,'This reviewed resume version is immutable. Upload a new version to change its source text.')
        if resume['updated_at']!=body.expected_updated_at:raise HTTPException(409,'This resume changed. Reopen its text review.')
        raw_file(user['id'],document)
        return db.save(user['id'],'resume',{**resume['data'],'source_text':body.text,'source_reviewed':True},resume['id'])


def removal_blocker(user,record):
    id=record['id']
    if record['kind']=='application' and any(a.get('kind')=='document' for a in record['data'].get('attachments',[])):return 'Remove uploaded files first, or archive this application.'
    if record['kind']=='job' and any(a['data'].get('job_id')==id and any(d.get('kind')=='document' for d in a['data'].get('attachments',[])) for a in db.list_entities(user,'application')):return 'Keep this posting to preserve its application document references.'
    if record['kind']=='document':
        if record['data'].get('purpose')=='application':return 'Remove this file using its application document controls.'
    if record['kind']=='resume' and record['data'].get('origin')=='uploaded':return 'Remove this uploaded resume using its application document controls.'
    return ''

@router.delete('/applications/{application_id}/documents/{document_id}')
def remove(application_id:str,document_id:str,user=Depends(auth.current)):
    uid=user['id']
    with applications.LOCK,db.connect() as c:
        c.execute('BEGIN IMMEDIATE');app,document=linked(uid,application_id,document_id);rid=document['data'].get('resume_id')
        if rid:
            for a in db.list_entities(uid,'application'):
                if a['data'].get('submitted_resume_id')==rid:raise HTTPException(409,'Select a different submitted resume before removing this version.')
                if a['id']!=application_id and rid in a['data'].get('resume_ids',[]):raise HTTPException(409,'This version is attached to another application.')
            if any(r['data'].get('resume_id')==rid for kind in ('cover_workspace','cover_revision','cover_letter') for r in db.list_entities(uid,kind)):
                raise HTTPException(409,'This resume is referenced by a cover letter. Keep it to preserve the exact source version.')
            for row in c.execute('SELECT payload FROM cc_runs WHERE user_id=?',(uid,)):
                if any(d['id']==rid for d in json.loads(row[0]).get('documents',[])):raise HTTPException(409,'This resume is referenced by an application assistant run.')
            app['data']['resume_ids']=[r for r in app['data'].get('resume_ids',[]) if r!=rid]
            if app['data'].get('workflow',{}).get('resume_id')==rid:app['data']['workflow']={'step':'resume','resume_id':'','cover_letter_id':'','cover_skipped':False}
            c.execute('DELETE FROM entities WHERE user_id=? AND id=?',(uid,rid))
        app['data']['attachments']=[a for a in app['data'].get('attachments',[]) if not(a['kind']=='document' and a['record_id']==document_id)]
        from .resume_conversation import write
        write(c,uid,'application',app['data'],app['id']);c.execute('DELETE FROM entities WHERE user_id=? AND id=?',(uid,document_id))
    (config.DATA_DIR/'uploads'/uid/document_id).unlink(missing_ok=True)
    return owned(uid,application_id,'application')


def validate_backup(record,kinds,by_id,files):
    data=record['data']
    if record['kind']=='document' and data.get('purpose')=='application':
        if kinds.get(data.get('application_id'))!='application' or record['id'] not in files or data.get('category') not in ('resume','cover_letter','interview_prep','email','other'):raise ValueError()
        app=by_id[data['application_id']]['data']
        if not any(a.get('kind')=='document' and a.get('record_id')==record['id'] for a in app.get('attachments',[])):raise ValueError()
    if record['kind']=='resume' and data.get('origin')=='uploaded':
        doc=by_id.get(data.get('document_id'),{})
        if kinds.get(data.get('document_id'))!='document' or doc['data'].get('purpose')!='application' or doc['data'].get('resume_id')!=record['id'] or doc['data'].get('category')!='resume':raise ValueError()
        app=by_id.get(doc['data'].get('application_id'),{}).get('data',{})
        if record['id'] not in app.get('resume_ids',[]) or data.get('job_id')!=app.get('job_id'):raise ValueError()
        if not isinstance(data.get('source_text'),str) or not isinstance(data.get('source_reviewed'),bool) or len(data['source_text'])>100000:raise ValueError()
