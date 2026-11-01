"""User-selected public website pages. Discovery reads supplied pages only, never a crawl."""
import asyncio,copy,hashlib,re
from pathlib import PurePosixPath
from urllib.parse import urlparse,urljoin,urlunparse,unquote
from bs4 import BeautifulSoup
from fastapi import HTTPException
from . import db,project_sources as sources,project_documents
from .network import public_fetch,ServiceError
from .models import validate_link

MAX_DISCOVERED=300

def canonical(url):
    try:
        url=validate_link(url.strip());p=urlparse(url)
        if not url or p.port not in (None,80,443) or len(url)>2000:raise ValueError()
        return urlunparse((p.scheme,p.netloc,p.path or '/',p.params,p.query,''))
    except ValueError:raise ServiceError('Use a complete public HTTP(S) link without credentials, on port 80 or 443.') from None

def same_site(url,root):
    p=urlparse(url);r=urlparse(root)
    if (p.hostname or '').lower().rstrip('.')!=(r.hostname or '').lower().rstrip('.'):return False
    if r.hostname=='sites.google.com':
        parts=[unquote(v) for v in r.path.split('/') if v]
        if len(parts)<2 or parts[0] not in ('view','site'):return False
        prefix='/'+parts[0]+'/'+parts[1]
        path=p.path
        for _ in range(3):path=unquote(path)
        if any(v in ('.','..') for v in path.split('/')):return False
        return path==prefix or path.startswith(prefix+'/')
    return True

def candidate(url,root,title='',suggested=False):
    url=canonical(url);p=urlparse(url);suffix=PurePosixPath(unquote(p.path)).suffix.lower()
    document=suffix in sources.EXTENSIONS- {'.html','.css','.js','.jsx','.ts','.tsx','.json','.xml','.sh','.conf','.properties','.yaml','.yml','.toml','.tf','.hcl'}
    if not document and (suffix not in ('','.html','.htm') or not same_site(url,root)):return None
    name=re.sub(r'[^a-zA-Z0-9_.-]+','-',PurePosixPath(unquote(p.path)).name)[:100] or 'page'
    if not document:name=name.rsplit('.',1)[0]+'.html'
    path=hashlib.sha256(url.encode()).hexdigest()[:16]+'/'+name
    if not sources.allowed(path):return None
    return {'file_path':path,'url':url,'website_url':url,'website_root':root,'website_kind':'document' if document else 'page','title':title[:300] or url,'size':0,'suggested':suggested}

def html_text(raw):
    soup=BeautifulSoup(raw,'html.parser');title=soup.title.get_text(' ',strip=True) if soup.title else ''
    links=[(a.get('href',''),a.get_text(' ',strip=True)) for a in soup.find_all('a',href=True)]
    for tag in soup(['script','style','nav','footer','header','noscript','form','iframe','svg']):tag.decompose()
    main=soup.find('main') or soup.find('article') or soup
    text=main.get_text('\n',strip=True)
    if re.search(r'^(sign in|log in|login|access denied|permission required)\b',title,re.I) and len(text)<3000:raise ServiceError('This page requires login or permission. Save it as a reference and upload or paste the material instead.')
    return title,text,links

async def read(info):
    page=await public_fetch(canonical(info['website_url']),10*1024*1024)
    if page['status']!=200:raise ServiceError('This page is unavailable or requires permission. Its link can still be saved as a reference; upload or paste the content instead.')
    final=canonical(page['url']);mime=page.get('content_type','').lower()
    if info['website_kind']=='page':
        if not same_site(final,info['website_root']):raise ServiceError('The page redirected outside this site. Save the destination separately if you want to import it.')
        if mime and not any(v in mime for v in ('text/html','text/plain','application/xhtml')):raise ServiceError('This page did not return readable website text. Upload a supported document instead.')
        title,text,links=html_text(page['content'])
        file=sources.extracted(info['file_path'],text.encode())
    else:
        if 'text/html' in mime:raise ServiceError('The document link returned a website or login page. Upload the document or paste its text instead.')
        file=await asyncio.to_thread(sources.extracted,info['file_path'],page['content']);title=info['title'];links=[]
        if file.get('visual_needed'):file['_visual_raw']=page['content']
    if not file.get('text','').strip() and not file.get('visual_needed'):raise ServiceError('No readable text was found. Upload or paste a readable copy instead.')
    return {**info,**file,'url':final,'title':title or info['title'],'size':len(page['content'])},links

async def discover(user,urls,experience_id=''):
    if experience_id:sources.require(user,experience_id,'experience')
    urls=list(dict.fromkeys(canonical(v) for v in urls))
    if not 1<=len(urls)<=5:raise HTTPException(400,'Choose one to five public website links.')
    available={};excluded=[]
    for root in urls:
        info=candidate(root,root,suggested=True)
        if not info:raise HTTPException(400,'Choose a public website page or supported document.')
        try:
            file,links=await read(info);available[file['file_path']]=file
            for href,title in links:
                try:value=candidate(urljoin(file['url'],href),root,title)
                except ServiceError:continue
                if value and value['file_path'] not in available and len(available)<MAX_DISCOVERED:available[value['file_path']]=value
        except ServiceError as error:
            available[info['file_path']]={**info,'read_error':str(error),'suggested':False};excluded.append({'file_path':info['file_path'],'reason':str(error)})
    files=list(available.values());created=project_documents.persist_entries(user,files)
    try:
        if sum(len(v.get('text','').encode()) for v in files)>sources.MAX_TOTAL:raise HTTPException(400,'The supplied pages exceed 2 MB extracted text. Load fewer links at once.')
        return db.save(user,'project_source',{'provider':'website','version':1,'label':'Website materials','url':urls[0],'urls':urls,'available_files':files,'excluded':excluded,'experience_id':experience_id,'archived':False})
    except Exception:project_documents.cleanup(user,created);raise

async def preview(user,id,paths):
    source=sources.require(user,id,'project_source');data=copy.deepcopy(source['data'])
    known={v['file_path']:v for v in data.get('available_files',[])}
    if not paths or len(paths)>30 or len(set(paths))!=len(paths) or set(paths)-known.keys():raise HTTPException(400,'Choose up to 30 different materials from this website source.')
    if any(not known[p].get('website_url') for p in paths):raise HTTPException(400,'Choose discovered website material to preview.')
    for path in paths:
        if 'text' in known[path]:continue
        try:
            value,_=await read(known[path]);known[path]=value
        except ServiceError as error:known[path]['read_error']=str(error)
    files=list(known.values())
    if sum(len(f.get('text','').encode()) for f in files)>sources.MAX_TOTAL:raise HTTPException(400,'The preview selection exceeds 2 MB extracted text. Your earlier source and selection are preserved; choose fewer pages.')
    created=project_documents.persist_entries(user,files)
    try:
        data.update(available_files=files,version=data.get('version',1)+1)
        # New source revision keeps earlier selections and snapshots immutable.
        return db.save(user,'project_source',data)
    except Exception:project_documents.cleanup(user,created);raise

async def selected(info):
    file,_=await read(info)
    return file

def validate_file(file):
    if file.get('website_url'):
        try:
            url=canonical(file['website_url']);root=canonical(file['website_root'])
            if file.get('website_kind') not in ('page','document') or file['website_kind']=='page' and not same_site(url,root):raise ValueError('Invalid website page boundary')
        except (KeyError,ServiceError):raise ValueError('Invalid website reference') from None
