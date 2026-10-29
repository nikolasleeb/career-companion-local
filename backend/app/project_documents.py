"""Local project document text/OCR and account-owned originals for explicit AI review."""
import base64,hashlib,io,os,posixpath,shutil,subprocess,tempfile,threading,zipfile
from pathlib import Path,PurePosixPath
from defusedxml import ElementTree as ET
from PIL import Image,ImageOps
from pypdf import PdfReader
from . import db,config,documents,certificate_ocr,storage
from .network import ServiceError

IMAGES={'.png','.jpg','.jpeg','.webp','.gif','.bmp','.tif','.tiff'}
OFFICE={'.pptx','.docx'}
DEFERRED={'.ppt':'application/vnd.ms-powerpoint','.doc':'application/msword','.xls':'application/vnd.ms-excel','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.rtf':'application/rtf','.odt':'application/vnd.oasis.opendocument.text'}
EXTENSIONS=IMAGES|OFFICE|set(DEFERRED)|{'.pdf'}
P='http://schemas.openxmlformats.org/presentationml/2006/main';A='http://schemas.openxmlformats.org/drawingml/2006/main';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
MIME={'.pdf':'application/pdf','.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',**DEFERRED}
_slots=threading.BoundedSemaphore(2)
NOTICE='[Local text unavailable. The selected original requires OpenAI file or visual review when Analyze is clicked.]'


def package(raw):
    try:
        z=zipfile.ZipFile(io.BytesIO(raw));entries=z.infolist();names=[m.filename for m in entries]
        if len(entries)>3000 or sum(m.file_size for m in entries)>64*1024*1024 or len(names)!=len(set(names)):raise ValueError()
        for m in entries:
            if m.flag_bits&1 or m.filename.startswith(('/','\\')) or '..' in m.filename.replace('\\','/').split('/') or m.file_size>16*1024*1024:raise ValueError()
            if 'vbaproject' in m.filename.lower() or '/embeddings/' in m.filename.lower():raise ServiceError('Macro-enabled documents and embedded executable objects are not supported. Export a PDF.')
            if m.filename.endswith('.rels'):
                for rel in ET.fromstring(z.read(m)):
                    if rel.get('TargetMode')=='External' and not rel.get('Type','').endswith('/hyperlink'):raise ServiceError('Externally linked images or resources are not supported. Export a self-contained document or PDF.')
        return z
    except ServiceError:raise
    except Exception:raise ServiceError('This Office file is corrupt, encrypted, or expands beyond the document limits.') from None


def xml(z,path):
    try:return ET.fromstring(z.read(path))
    except Exception:raise ServiceError('This Office document contains unreadable XML.') from None

def relations(z,part):
    path=str(PurePosixPath(part).parent/'_rels'/(PurePosixPath(part).name+'.rels'))
    if path not in z.namelist():return {}
    result={}
    for rel in xml(z,path):
        if rel.get('TargetMode')=='External':continue
        target=rel.get('Target','');target=posixpath.normpath(target.lstrip('/') if target.startswith('/') else str(PurePosixPath(part).parent/target))
        if target.startswith('../') or target not in z.namelist():raise ServiceError('This presentation contains an invalid part reference.')
        result[rel.get('Id')]=(target,rel.get('Type',''))
    return result

def paragraphs(root):return [''.join(n.text or '' for n in p.iter('{'+A+'}t')).strip() for p in root.iter('{'+A+'}p')]


def pptx(raw):
    with package(raw) as z:
        rels=relations(z,'ppt/presentation.xml');root=xml(z,'ppt/presentation.xml');slides=list(root.findall('./{'+P+'}sldIdLst/{'+P+'}sldId'))
        if not 1<=len(slides)<=100:raise ServiceError('Choose a presentation with 1 to 100 slides.')
        parts=[]
        for number,slide in enumerate(slides,1):
            target,kind=rels.get(slide.get('{'+R+'}id'),('',''))
            if not kind.endswith('/slide') or not target.startswith('ppt/slides/'):raise ServiceError('The presentation slide order could not be read.')
            body='\n'.join(filter(None,paragraphs(xml(z,target))));parts.append('Slide '+str(number)+'\n'+body)
            for path,kind in relations(z,target).values():
                if kind.endswith('/notesSlide'):
                    notes=[]
                    for shape in xml(z,path).iter('{'+P+'}sp'):
                        ph=shape.find('.//{'+P+'}ph')
                        if ph is not None and ph.get('type') in ('sldNum','dt','hdr','ftr','sldImg'):continue
                        notes.extend(filter(None,paragraphs(shape)))
                    if notes:parts.append('Speaker notes for slide '+str(number)+'\n'+'\n'.join(notes))
        has_visuals=any(n.startswith(('ppt/media/','ppt/charts/','ppt/diagrams/')) for n in z.namelist())
    return {'text':'\n\n'.join(parts),'pages':len(slides),'visual_needed':has_visuals,'review_kind':'pdf','warnings':['Embedded slide images, charts and diagrams will be included for OpenAI visual review when Analyze is clicked.'] if has_visuals else []}


def normalize_image(raw):
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in ('PNG','JPEG','WEBP','GIF','BMP','TIFF') or original.width*original.height>40_000_000:raise ValueError()
            frames=getattr(original,'n_frames',1);original.seek(0);image=ImageOps.exif_transpose(original).convert('RGBA');image.thumbnail((3000,3000))
            background=Image.new('RGBA',image.size,'white');background.alpha_composite(image);output=io.BytesIO();background.convert('RGB').save(output,format='PNG')
            return output.getvalue(),frames
    except Exception:raise ServiceError('This image is unreadable or exceeds 40 megapixels. Export a smaller PNG or JPEG.') from None


def read(path,raw):
    suffix=PurePosixPath(path).suffix.lower();warnings=[]
    if suffix in IMAGES:
        normalized,frames=normalize_image(raw);result=certificate_ocr.extract(normalized,'image/png');text='\n'.join('Page '+str(n)+'\n'+'\n'.join(lines) for n,lines in result['pages'] if lines)
        warnings=list(result['warnings']);needed=True
        warnings.append('Image OCR may miss diagrams, handwriting and small text. The original will also be included when Analyze is clicked.')
        if frames>1:warnings.append('Only the first image frame was read; upload additional frames separately.');needed=True
        return {'text':text or NOTICE,'pages':1,'visual_needed':needed,'review_kind':'image','warnings':warnings,'mime':'image/'+({'jpg':'jpeg','tif':'tiff'}.get(suffix[1:],suffix[1:]))}
    if suffix=='.pptx':return {**pptx(raw),'mime':MIME[suffix]}
    if suffix=='.pdf':
        try:
            pdf=PdfReader(io.BytesIO(raw))
            if pdf.is_encrypted:raise ServiceError('Upload an unlocked PDF.')
            if not 1<=len(pdf.pages)<=100:raise ServiceError('Choose a PDF with 1 to 100 pages.')
            texts=[page.extract_text() or '' for page in pdf.pages]
        except ServiceError:raise
        except Exception:raise ServiceError('This PDF could not be read. Export a new PDF.') from None
        missing=[i+1 for i,t in enumerate(texts) if len(t.strip())<30]
        if missing:
            result=certificate_ocr.extract(raw,'application/pdf',missing)
            for n,lines in result['pages']:
                if lines:texts[n-1]='\n'.join(lines)
            warnings.extend(result['warnings']);warnings.append('Pages with little native text were read with local OCR and will also be included for OpenAI visual review.')
        return {'text':'\n\n'.join('Page '+str(i+1)+'\n'+t for i,t in enumerate(texts)) if any(t.strip() for t in texts) else NOTICE,'pages':len(texts),'visual_needed':bool(missing),'review_kind':'pdf','warnings':warnings,'mime':MIME[suffix]}
    if suffix=='.docx':
        with package(raw) as z:has_visuals=any(n.startswith(('word/media/','word/charts/','word/diagrams/')) for n in z.namelist())
        try:value=documents.extract(path,raw);text=value['text'];pages=value['pages']
        except ServiceError as error:
            if 'No readable text' not in str(error):raise
            text=NOTICE;pages=documents.docx_pages(raw);has_visuals=True
        return {'text':text,'pages':pages,'visual_needed':has_visuals,'review_kind':'pdf','warnings':['Embedded document images will be included for OpenAI visual review.'] if has_visuals else [],'mime':MIME[suffix]}
    if suffix in DEFERRED:
        if suffix in ('.ppt','.doc','.xls') and not raw.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):raise ServiceError('This legacy Office file is not valid. Export a current Office file or PDF.')
        if suffix in ('.xlsx','.odt'):
            with package(raw):pass
        if suffix=='.rtf' and not raw.lstrip().startswith(b'{\\rtf'):raise ServiceError('This is not a readable RTF document.')
        return {'text':NOTICE,'pages':0,'visual_needed':True,'review_kind':'file','warnings':['This format will be read by OpenAI only when Analyze is clicked. Non-PDF file input reads text; export to PDF for visual charts or diagrams.'],'mime':DEFERRED[suffix]}
    raise ServiceError('Unsupported project document format.')


def save_original(user,path,raw,entry):
    digest=hashlib.sha256(raw).hexdigest()
    for row in db.list_entities(user,'document'):
        if row['data'].get('purpose')=='project_material' and row['data'].get('sha256')==digest and (config.DATA_DIR/'uploads'/user/row['id']).is_file():return row['id'],False
    storage.ensure_capacity(len(raw)+65536)
    row=db.save(user,'document',{'filename':PurePosixPath(path).name[:200],'purpose':'project_material','mime':entry['mime'],'format':PurePosixPath(path).suffix.lower()[1:],'size':len(raw),'sha256':digest,'pages':entry.get('pages',0),'text':'','reviewed':False})
    folder=config.DATA_DIR/'uploads'/user;folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:storage.write_bytes(folder/row['id'],raw)
    except Exception:db.delete(user,row['id']);raise
    return row['id'],True


def render_office(raw,suffix):
    with package(raw):pass
    if not _slots.acquire(timeout=1):raise ServiceError('Document conversion is busy. Retry after the current conversion finishes; no OpenAI request was started.')
    try:
        binary=shutil.which('libreoffice') or shutil.which('soffice')
        if not binary:raise ServiceError('Local Office rendering is unavailable. Upload a PDF for visual review.')
        with tempfile.TemporaryDirectory(prefix='career-project-render-') as folder:
            root=Path(folder);source=root/('input'+suffix);source.write_bytes(raw);profile=root/'profile';registry=profile/'user';registry.mkdir(parents=True)
            (registry/'registrymodifications.xcu').write_text('<oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>')
            try:subprocess.run([binary,'-env:UserInstallation='+profile.as_uri(),'--headless','--nologo','--nodefault','--norestore','--convert-to','pdf','--outdir',str(root),str(source)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=45,check=True,env={'PATH':os.defpath,'LANG':'C.UTF-8','HOME':folder,'TMPDIR':folder,'XDG_CACHE_HOME':str(root/'cache')})
            except (OSError,subprocess.SubprocessError):raise ServiceError('The Office preview could not finish. Export a PDF and upload it; no OpenAI request was started.') from None
            try:result=(root/'input.pdf').read_bytes()
            except OSError:raise ServiceError('The Office preview could not be produced. Export a PDF; no OpenAI request was started.') from None
            if len(result)>32*1024*1024:raise ServiceError('The rendered PDF exceeds 32 MB. Export a smaller PDF.')
            pages=len(PdfReader(io.BytesIO(result)).pages)
            if not 1<=pages<=100:raise ServiceError('The rendered document exceeds 100 pages. Upload the relevant pages as PDF.')
            return result,pages
    finally:_slots.release()


def attachment(user,file):
    row=db.get(user,file.get('visual_document_id',''),'document')
    if not row or row['data'].get('purpose')!='project_material':raise ServiceError('The original project file is unavailable for visual review. Upload it again before analyzing.')
    path=config.DATA_DIR/'uploads'/user/row['id']
    if not path.is_file():raise ServiceError('The original project file is missing. Restore it from an account backup or upload it again.')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=row['data']['sha256'] or row['data']['sha256']!=file.get('original_sha256'):raise ServiceError('The original project file changed. Upload it again; no OpenAI request was started.')
    suffix='.'+row['data']['format'];pages=file.get('pages',1)
    if file['review_kind']=='image':
        raw,_=normalize_image(raw);value={'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(raw).decode(),'detail':'high'}
    else:
        if suffix in OFFICE:raw,pages=render_office(raw,suffix);suffix='.pdf'
        mime='application/pdf' if suffix=='.pdf' else row['data']['mime']
        value={'type':'input_file','filename':PurePosixPath(file['file_path']).stem[:140]+suffix,'file_data':'data:'+mime+';base64,'+base64.b64encode(raw).decode()}
        if suffix=='.pdf':value['detail']='high'
    return value,pages


def persist_entries(user,entries):
    created=[]
    try:
        for entry in entries:
            raw=entry.pop('_visual_raw',None)
            if raw is None:continue
            identity,new=save_original(user,entry['file_path'],raw,entry)
            entry['visual_document_id']=identity
            if new:created.append(identity)
        return created
    except Exception:
        cleanup(user,created);raise


def cleanup(user,identities):
    from .account_cleanup import refs
    for identity in identities:
        if any(refs(r['data'],{identity}) for kind in ('project_source','project_snapshot') for r in db.list_entities(user,kind)):continue
        (config.DATA_DIR/'uploads'/user/identity).unlink(missing_ok=True);db.delete(user,identity)


def visual_files(user,files):
    selected=[f for f in files if f.get('visual_needed')]
    if len(selected)>8:raise ServiceError('Select at most eight files needing OpenAI file or visual review per analysis.')
    pages=sum(max(1,f.get('pages',1)) for f in selected)
    if pages>120:raise ServiceError('Select at most 120 pages/slides needing OpenAI review per analysis.')
    total=0
    for f in selected:
        row=db.get(user,f.get('visual_document_id',''),'document')
        if not row or row['data'].get('purpose')!='project_material' or row['data'].get('sha256')!=f.get('original_sha256'):raise ServiceError('A selected original project file is unavailable or changed. Upload it again before analyzing.')
        total+=row['data']['size']
    if total>32*1024*1024:raise ServiceError('Selected originals exceed the 32 MB AI attachment budget. Select fewer files.')
    return selected,pages


def _validate_original(data,raw):
    if not raw or len(raw)>10*1024*1024 or len(raw)!=data.get('size') or hashlib.sha256(raw).hexdigest()!=data.get('sha256'):raise ValueError('Invalid original project file')
    suffix='.'+data.get('format','')
    if suffix not in EXTENSIONS:raise ValueError('Unsupported original project file')
    if suffix in IMAGES:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>40_000_000 or im.format not in ('PNG','JPEG','WEBP','GIF','BMP','TIFF'):raise ValueError('Invalid image')
    elif suffix=='.pdf':
        pdf=PdfReader(io.BytesIO(raw))
        if pdf.is_encrypted or not 1<=len(pdf.pages)<=100:raise ValueError('Invalid PDF')
    elif suffix in ('.pptx','.docx','.xlsx','.odt'):
        with package(raw):pass
    elif suffix in ('.ppt','.doc','.xls') and not raw.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):raise ValueError('Invalid legacy Office file')
    elif suffix=='.rtf' and not raw.lstrip().startswith(b'{\\rtf'):raise ValueError('Invalid RTF')


def validate_original(data,raw):
    try:_validate_original(data,raw)
    except Exception:raise ValueError('Invalid original project file in backup') from None
