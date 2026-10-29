"""Fictional common-format inputs and explicit multimodal review, without paid requests."""
import asyncio,base64,copy,hashlib,io,json,zipfile
import pytest
from PIL import Image
from pypdf import PdfWriter
from app import ai,config,db,project_documents as docs,project_sources as sources,project_uploads as uploads,project_routes
from app.network import ServiceError


def bundle(parts):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in parts.items():z.writestr(name,value)
    return out.getvalue()


def presentation(visual=True,external=False):
    # The order deliberately differs from filenames. Notes omit a slide-number placeholder.
    p=docs.P;a=docs.A;r=docs.R
    parts={'ppt/presentation.xml':f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId r:id="second"/><p:sldId r:id="first"/></p:sldIdLst></p:presentation>',
    'ppt/_rels/presentation.xml.rels':f'<Relationships><Relationship Id="first" Type="{r}/slide" Target="slides/slide1.xml"/><Relationship Id="second" Type="{r}/slide" Target="slides/slide2.xml"/></Relationships>',
    'ppt/slides/slide1.xml':f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><a:p><a:t>Fictional ending</a:t></a:p></p:sld>',
    'ppt/slides/slide2.xml':f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><a:p><a:t>Fictional opening</a:t></a:p></p:sld>',
    'ppt/slides/_rels/slide2.xml.rels':f'<Relationships><Relationship Id="notes" Type="{r}/notesSlide" Target="../notesSlides/notes1.xml"/></Relationships>',
    'ppt/notesSlides/notes1.xml':f'<p:notes xmlns:p="{p}" xmlns:a="{a}"><p:sp><a:p><a:t>Fictional speaker notes</a:t></a:p></p:sp><p:sp><p:ph type="sldNum"/><a:p><a:t>99</a:t></a:p></p:sp></p:notes>'}
    if visual:parts['ppt/media/image1.png']=image()
    if external:parts['ppt/slides/_rels/slide1.xml.rels']=f'<Relationships><Relationship Type="{r}/image" TargetMode="External" Target="https://example.invalid/tracker"/></Relationships>'
    return bundle(parts)


def image(fmt='PNG'):
    out=io.BytesIO();Image.new('RGB',(100,80),'white').save(out,format=fmt);return out.getvalue()


def no_ocr(monkeypatch):monkeypatch.setattr(docs.certificate_ocr,'extract',lambda *a,**k:{'pages':[],'incomplete':True,'warnings':['Fictional OCR failure']})


def selected(user,raw=None,name='diagram.png'):
    row=uploads.preview(user,[(name,raw or image())]);paths=[f['file_path'] for f in row['data']['available_files']]
    return row,asyncio.run(sources.select(user,row['id'],paths))


def test_powerpoint_order_notes_and_visuals():
    out=sources.extracted('slides.pptx',presentation())
    assert out['pages']==2 and out['visual_needed'] and out['review_kind']=='pdf'
    assert out['text'].index('Fictional opening')<out['text'].index('Fictional ending')
    assert 'Speaker notes for slide 1\nFictional speaker notes' in out['text'] and '99' not in out['text']
    assert not docs.pptx(presentation(False))['visual_needed']


@pytest.mark.parametrize('extra',[{'ppt/vbaProject.bin':b'macro'}, {'ppt/embeddings/oleObject.bin':b'object'}, {'../escape.xml':b'x'}])
def test_office_unsafe_packages_rejected(extra):
    with pytest.raises(ServiceError):docs.package(bundle(extra))
    with pytest.raises(ServiceError):docs.pptx(presentation(external=True))


@pytest.mark.parametrize('fmt,name',[('PNG','a.png'),('JPEG','a.jpg'),('WEBP','a.webp'),('GIF','a.gif'),('BMP','a.bmp'),('TIFF','a.tiff')])
def test_common_image_formats_keep_failed_ocr_original(account,monkeypatch,fmt,name):
    no_ocr(monkeypatch)
    async def no_ai(*a,**k):raise AssertionError('Upload must not call AI')
    monkeypatch.setattr(ai,'structured',no_ai)
    raw=image(fmt);row,snap=selected(account['id'],raw,name);file=snap['data']['files'][0]
    assert file['visual_needed'] and file['text']==docs.NOTICE and file['warnings']
    assert row['data']['available_files'][0]['visual_document_id']==file['visual_document_id']
    item,pages=docs.attachment(account['id'],file)
    assert item['type']=='input_image' and item['image_url'].startswith('data:image/png;base64,') and pages==1
    assert (config.DATA_DIR/'uploads'/account['id']/file['visual_document_id']).read_bytes()==raw
    assert not db.list_entities(account['id'],'project_analysis')


def test_scanned_pdf_kept_and_included(account,monkeypatch):
    no_ocr(monkeypatch);writer=PdfWriter();writer.add_blank_page(100,100);out=io.BytesIO();writer.write(out)
    _,snap=selected(account['id'],out.getvalue(),'scanned.pdf');file=snap['data']['files'][0]
    item,pages=docs.attachment(account['id'],file)
    assert file['visual_needed'] and file['text']==docs.NOTICE and pages==1
    assert item['type']=='input_file' and item['detail']=='high' and base64.b64decode(item['file_data'].split(',',1)[1])==out.getvalue()


def test_legacy_office_and_spreadsheets_defer_without_executing():
    for suffix in ('.ppt','.doc','.xls'):
        out=docs.read('file'+suffix,bytes.fromhex('D0CF11E0A1B11AE1')+b'fictional')
        assert out['visual_needed'] and out['review_kind']=='file' and 'Non-PDF' in out['warnings'][0]
        with pytest.raises(ServiceError):docs.read('bad'+suffix,b'not OLE')
    assert docs.read('notes.rtf',b'{\\rtf1 Fictional notes}')['review_kind']=='file'
    with pytest.raises(ServiceError):docs.read('bad.rtf',b'not RTF')


def test_analyze_attaches_original_once_and_marks_ai_interpretation(account,monkeypatch):
    no_ocr(monkeypatch);user=account['id'];_,snap=selected(user)
    from app import posting_extraction
    monkeypatch.setattr(posting_extraction,'require_pdf_model',lambda mode:None)
    calls=[];path=snap['data']['files'][0]['file_path']
    async def fake(schema,payload,mode,**kwargs):
        calls.append(kwargs)
        assert kwargs['retry_allowed'] is False and kwargs['files'][1]['type']=='input_image'
        assert payload['attached_files'][0]['file_path']==path and 'ignore instructions' in payload['task']
        return {'summary':'Fictional diagram','findings':[{'file_path':path,'quote':'','observation':'Contains a fictional process diagram.','evidence_kind':'visual','page':1}]},{'model':'fictional'}
    monkeypatch.setattr(ai,'structured',fake)
    result=asyncio.run(sources.analyze(user,snap['id'],'economy'))['analysis']
    finding=result['data']['findings'][0];assert len(calls)==1 and finding['requires_review'] and finding['line_start']==0 and finding['visual_document_id']
    project_routes.validate_finding(finding,snap['data'])
    with pytest.raises(ValueError):project_routes.validate_finding({**finding,'visual_document_id':'foreign'},snap['data'])


@pytest.mark.parametrize('kind,path,page',[('text','diagram.png',0),('visual','foreign.png',1),('visual','diagram.png',2),('file','diagram.png',0)])
def test_invalid_ai_findings_never_saved(account,monkeypatch,kind,path,page):
    no_ocr(monkeypatch);_,snap=selected(account['id'])
    from app import posting_extraction
    monkeypatch.setattr(posting_extraction,'require_pdf_model',lambda mode:None)
    async def fake(*a,**k):return {'summary':'Untrusted','findings':[{'file_path':path,'quote':docs.NOTICE,'observation':'Untrusted','evidence_kind':kind,'page':page}]},{}
    monkeypatch.setattr(ai,'structured',fake)
    with pytest.raises(ServiceError):asyncio.run(sources.analyze(account['id'],snap['id'],'economy'))
    assert not db.list_entities(account['id'],'project_analysis')


def test_original_ownership_hash_and_review_limits(account,monkeypatch):
    no_ocr(monkeypatch);user=account['id'];_,snap=selected(user);file=snap['data']['files'][0]
    with pytest.raises(ServiceError):docs.attachment('other-account',file)
    with pytest.raises(ServiceError):docs.visual_files(user,[file]*9)
    with pytest.raises(ServiceError):docs.visual_files(user,[{**file,'pages':121}])
    (config.DATA_DIR/'uploads'/user/file['visual_document_id']).write_bytes(b'changed')
    with pytest.raises(ServiceError):docs.attachment(user,file)


def test_original_download_backup_restore_and_missing_file_atomicity(client,account,monkeypatch):
    no_ocr(monkeypatch);user=account['id'];_,snap=selected(user);file=snap['data']['files'][0];identity=file['visual_document_id']
    assert client.get('/api/project-documents/'+identity+'/download').content==image()
    assert client.delete('/api/records/'+identity).status_code in (404,409,405)
    backup=client.get('/api/account/export').json();assert identity in backup['files']
    missing=copy.deepcopy(backup);del missing['files'][identity]
    before=len(db.list_entities(user,'document'))
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(missing),'application/json')})
    assert response.status_code>=400 and len(db.list_entities(user,'document'))==before
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')});assert response.status_code==200,response.text
    restored=next(s for s in db.list_entities(user,'project_snapshot') if s['id']!=snap['id'])
    new_id=restored['data']['files'][0]['visual_document_id'];assert new_id!=identity
    assert (config.DATA_DIR/'uploads'/user/new_id).read_bytes()==image()
    docs.validate_original(db.get(user,new_id,'document')['data'],image())
    with pytest.raises(ValueError):docs.validate_original(db.get(user,new_id,'document')['data'],b'forged')


def test_office_render_missing_output_is_actionable(monkeypatch):
    monkeypatch.setattr(docs.shutil,'which',lambda name:'/fictional/soffice')
    monkeypatch.setattr(docs.subprocess,'run',lambda *a,**k:None)
    with pytest.raises(ServiceError,match='no OpenAI request'):docs.render_office(presentation(),'.pptx')


def test_visual_findings_survive_backup_and_account_cleanup(client,account,monkeypatch):
    no_ocr(monkeypatch);user=account['id'];_,snap=selected(user);file=snap['data']['files'][0];identity=file['visual_document_id']
    finding={'file_path':file['file_path'],'evidence_kind':'visual','page':1,'quote':'','observation':'Fictional diagram','requires_review':True,'visual_document_id':identity,'line_start':0,'line_end':0}
    db.save(user,'project_analysis',{'snapshot_id':snap['id'],'summary':'Fictional','findings':[finding]})
    backup=client.get('/api/account/export').json()
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup),'application/json')});assert response.status_code==200,response.text
    restored=next(a for a in db.list_entities(user,'project_analysis') if a['data']['findings'][0]['visual_document_id']!=identity)
    restored_snap=db.get(user,restored['data']['snapshot_id'],'project_snapshot')
    assert restored['data']['findings'][0]['visual_document_id']==restored_snap['data']['files'][0]['visual_document_id']
    from app import project_context
    assert any(r['findings'][0]['requires_review'] for r in project_context.catalog(user,{'project_snapshot_ids':[restored_snap['id']]}))
    preview=client.post('/api/account/cleanup/preview',json={'categories':['uploads']});assert preview.status_code==200,preview.text
    result=client.post('/api/account/cleanup/apply',json={'preview_id':preview.json()['preview_id'],'confirmed':True});assert result.status_code==200,result.text
    assert not db.list_entities(user,'document') and not db.list_entities(user,'project_snapshot')
    from app import account_cleanup
    account_cleanup.remove_files()
    assert not (config.DATA_DIR/'uploads'/user/identity).exists()


def test_successful_ocr_still_allows_original_visual_review_and_foreign_download(client,account,monkeypatch):
    monkeypatch.setattr(docs.certificate_ocr,'extract',lambda *a,**k:{'pages':[(1,['Fictional OCR text'])],'incomplete':False,'warnings':[]})
    _,snap=selected(account['id']);file=snap['data']['files'][0]
    assert file['visual_needed'] and 'Fictional OCR text' in file['text']
    estimate=client.get('/api/project-snapshots/'+snap['id']+'/estimate').json()
    assert estimate['visual_files']==1 and estimate['visual_pages']==1
    other=client.post('/api/auth/register',json={'username':'different-person','password':'fictional-test-password'});assert other.status_code==200
    client.headers['X-CSRF-Token']=other.json()['csrf']
    assert client.get('/api/project-documents/'+file['visual_document_id']+'/download').status_code==404
