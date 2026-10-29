"""Bounded project ZIP/text previews. Members are read in memory, never extracted or run."""
import hashlib
import io
import json
import re
import stat
import zipfile
import zlib
from pathlib import PurePosixPath
from fastapi import HTTPException
from . import db, project_sources as sources, project_documents
from .network import ServiceError

MAX_UPLOAD=32*1024*1024
MAX_MEMBER=10*1024*1024
MAX_EXPANDED=64*1024*1024
MAX_MEMBERS=1000
MAX_CANDIDATES=300
SECRET=re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|aws_secret_access_key\s*[=:]\s*[\"\']?[^\s\"\']{12}',re.I)

def links(values):
    from .models import validate_link
    values=list(dict.fromkeys(v.strip() for v in values if v.strip()))
    if len(values)>5:raise HTTPException(400,'Add at most five project links.')
    try:
        for value in values:validate_link(value)
    except ValueError:raise HTTPException(400,'Use complete public http:// or https:// project links without credentials.') from None
    return values

def preview(user,uploads,experience_id=''):
    if experience_id:sources.require(user,experience_id,'experience')
    if not uploads or len(uploads)>30:raise HTTPException(400,'Choose one to 30 uploads.')
    if sum(len(raw) for _,raw in uploads)>MAX_UPLOAD:raise HTTPException(413,'This upload exceeds 32 MB.')
    files=[];excluded=[];seen=set();text_bytes=0;expanded=0
    def omit(path,reason):
        if len(excluded)<1000:excluded.append({'file_path':path[:500],'reason':reason})
    def add(path,raw,archive=''):
        nonlocal text_bytes
        if len(path)>500 or not safe_path(path) or path in seen or not sources.allowed(path):
            omit(path,'Unsupported, duplicate, generated, dependency, or credential-like file');return
        seen.add(path)
        if len(files)>=MAX_CANDIDATES:omit(path,'300 readable preview files limit');return
        if SECRET.search(raw):omit(path,'Recognizable access key or private credential content');return
        try:entry=sources.extracted(path,raw)
        except ServiceError as error:omit(path,str(error));return
        if not entry['text'].strip():omit(path,'No readable text');return
        size=len(entry['text'].encode())
        if text_bytes+size>sources.MAX_TOTAL:omit(path,'2 MB extracted preview text limit');return
        text_bytes+=size
        if entry.get('visual_needed'):entry['_visual_raw']=raw
        files.append({**entry,'size':len(raw),'suggested':True,'archive':archive,'original_sha256':hashlib.sha256(raw).hexdigest()})
    for filename,raw in uploads:
        filename=filename.replace('\\','/')
        if PurePosixPath(filename).suffix.lower()!='.zip':
            if len(raw)>MAX_MEMBER:omit(filename,'File exceeds 10 MB');continue
            add(filename,raw);continue
        # Disallow a client-supplied traversal name even though no filesystem writes occur.
        if not safe_path(filename):omit(filename,'Unsafe archive name');continue
        archive=PurePosixPath(filename).name
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
                members=bundle.infolist()
                if len(members)>MAX_MEMBERS:raise HTTPException(400,'A ZIP may contain at most 1,000 entries. Upload a smaller project export.')
                expanded+=sum(m.file_size for m in members)
                if expanded>MAX_EXPANDED:raise HTTPException(413,'ZIP contents exceed the 64 MB expanded limit. Upload source code and reports separately from large datasets.')
                for member in members:
                    inner=member.filename.replace('\\','/');path=archive+'/'+inner
                    if member.is_dir():continue
                    mode=member.external_attr>>16
                    if not safe_path(inner) or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0,stat.S_IFREG):
                        omit(path,'Unsafe path or non-regular archive member');continue
                    if member.flag_bits&1:omit(path,'Encrypted ZIP members are not supported');continue
                    if member.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):omit(path,'Unsupported ZIP compression; use standard ZIP deflate');continue
                    if not sources.allowed(path):omit(path,'Nested archive, binary, generated, dependency, or credential-like file');continue
                    if member.file_size>MAX_MEMBER:omit(path,'File exceeds 10 MB');continue
                    if member.file_size>1024*1024 and member.file_size/max(1,member.compress_size)>200:omit(path,'Excessive ZIP compression ratio');continue
                    try:
                        with bundle.open(member) as stream:content=stream.read(MAX_MEMBER+1)
                        if len(content)>MAX_MEMBER or len(content)!=member.file_size:omit(path,'Invalid or oversized ZIP member');continue
                        add(path,content,archive)
                    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,EOFError,OSError,zlib.error):omit(path,'ZIP member could not be read')
        except (zipfile.BadZipFile,EOFError,OSError):raise HTTPException(400,'This ZIP could not be read. Export a standard, unencrypted ZIP or upload individual files.') from None
    if not files:raise HTTPException(400,'No readable project files. Upload code, notebooks, Office documents, PDFs or images in a standard ZIP or as individual files.')
    created=project_documents.persist_entries(user,files)
    try:return db.save(user,'project_source',{'version':1,'provider':'upload_preview','label':uploads[0][0][:200]+(' and other files' if len(uploads)>1 else ''),'available_files':files,'excluded':excluded,'experience_id':experience_id,'urls':[],'archived':False})
    except Exception:project_documents.cleanup(user,created);raise

def safe_path(path):
    p=PurePosixPath(path)
    return bool(path) and not p.is_absolute() and '..' not in p.parts and not re.match(r'^[A-Za-z]:',path) and '\x00' not in path

def combine(user,ids,urls,experience_id=''):
    if not ids or len(ids)>5 or len(set(ids))!=len(ids):raise HTTPException(400,'Combine one to five different project sources.')
    if experience_id:sources.require(user,experience_id,'experience')
    urls=links(urls);files=[];excluded=[];members=[];seen={};total=0
    for identity in ids:
        row=sources.require(user,identity,'project_source');data=row['data']
        if data['provider'] in ('upload','paste'):
            saved=next((r for r in db.list_entities(user,'project_snapshot') if r['data'].get('source_id')==identity),None)
            if not saved:raise HTTPException(400,'This source has no saved readable files.')
            data={**data,'available_files':saved['data']['files']}
        elif data['provider'] not in ('github','upload_preview','mixed'):raise HTTPException(400,'Choose a file-picker source.')
        for f in data.get('available_files',[]):
            entry=dict(f)
            entry.setdefault('size',len(entry.get('text','').encode()));entry.setdefault('suggested',True)
            if data['provider']=='github':entry.update(source_repo=f.get('source_repo',data['repo']),source_url=f.get('source_url',data['url']),source_commit=f.get('source_commit',data['commit']),original_path=f.get('original_path',f['file_path']))
            key=entry['file_path']
            if key in seen:
                if seen[key]==entry:continue
                key=identity[:8]+'/'+key;entry['file_path']=key
            if len(key)>500 or len(files)>=3000:excluded.append({'file_path':key[:500],'reason':'Combined file list limit'});continue
            total+=len(entry.get('text','').encode())
            if total>sources.MAX_TOTAL:raise HTTPException(400,'Combined uploads exceed 2 MB extracted text. Use a smaller set of files.')
            seen[key]=entry;files.append(entry)
        excluded.extend(data.get('excluded',[]));members.extend(data.get('members',[]) or ([{'repo':data['repo'],'url':data['url'],'commit':data['commit']} ] if data['provider']=='github' else []))
    if not files:raise HTTPException(400,'Choose a source with readable project files.')
    signature=hashlib.sha256(json.dumps({'files':files,'urls':urls,'experience_id':experience_id},sort_keys=True).encode()).hexdigest()
    existing=next((r for r in db.list_entities(user,'project_source') if r['data'].get('signature')==signature and not r['data'].get('archived')),None)
    if existing:return existing
    return db.save(user,'project_source',{'signature':signature,'version':1,'provider':'mixed','label':'Project uploads and links','repo':'Project materials','urls':urls,'url':urls[0] if urls else '','available_files':files,'excluded':excluded[:1000],'members':members[:10],'experience_id':experience_id,'archived':False})
