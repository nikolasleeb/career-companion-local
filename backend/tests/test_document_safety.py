import asyncio,io,json,zipfile
import pytest
from app import config,db,documents
from app.network import ServiceError


def test_docx_rejects_traversal_before_converter(monkeypatch):
    def no_converter(raw):raise AssertionError('Unsafe archive reached converter')
    monkeypatch.setattr(documents,'docx_pages',no_converter)
    for bad in ('../escape','/absolute','..\\escape'):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr('word/document.xml','<root/>');archive.writestr(bad,'x')
        with pytest.raises(ServiceError,match='unsafe archive paths'):documents.extract('fictional.docx',buffer.getvalue())


def test_docx_rejects_external_templates_before_converter(monkeypatch):
    def no_converter(raw):raise AssertionError('External template reached converter')
    monkeypatch.setattr(documents,'docx_pages',no_converter)
    for kind in ('attachedTemplate','image','oleObject'):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr('word/document.xml','<root/>')
            archive.writestr('word/_rels/document.xml.rels',f'<Relationships><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" TargetMode="External" Target="http://127.0.0.1/secret"/></Relationships>')
        with pytest.raises(ServiceError,match='Externally linked'):documents.extract('fictional.docx',buffer.getvalue())


def test_global_request_limit_rejects_without_starting_work():
    from app.security import ResourceBoundary
    sent=[];called=[]
    async def endpoint(*args):called.append(True)
    async def receive():return {'type':'http.request','body':b''}
    async def send(message):sent.append(message)
    boundary=ResourceBoundary(endpoint);boundary.active=16
    asyncio.run(boundary({'type':'http','path':'/api/me','method':'GET'},receive,send))
    assert sent[0]['status']==503 and not called and boundary.active==16




def test_converter_concurrency_is_bounded_across_tasks(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading,time
    lock=threading.Lock();active=0;peak=0
    def convert(raw):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active)
        try:time.sleep(.03);return b'fictional-pdf'
        finally:
            with lock:active-=1
    monkeypatch.setattr(documents,'_docx_pdf',convert)
    with ThreadPoolExecutor(6) as pool:results=list(pool.map(documents.docx_pdf,[b'fictional']*6))
    assert results==[b'fictional-pdf']*6
    assert peak==2
