import asyncio
import io
import json
import stat
import zipfile
import pytest
from fastapi import HTTPException
from app import ai,db,project_sources as sources,project_uploads as uploads
from app.models import ExperienceItem
from app.security import request_limit


def archive(entries,compression=zipfile.ZIP_DEFLATED):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=compression) as z:
        for name,text in entries:z.writestr(name,text)
    return buffer.getvalue()

def project(user):return db.save(user,'experience',ExperienceItem(title='Fictional AWS Spark project',category='project',confirmed=True).model_dump())

def test_zip_preview_selection_and_mixed_github_preserve_provenance_without_ai(client,account,monkeypatch):
    async def no_ai(*args,**kwargs):raise AssertionError('No AI before Analyze')
    monkeypatch.setattr(ai,'structured',no_ai);user=account['id'];record=project(user)
    notebook=json.dumps({'cells':[{'cell_type':'code','source':['print("historical")'],'outputs':[{'text':['not rerun']}]}]})
    raw=archive([('aws/collect.py','import boto3\nprint("never execute")'),('spark/pipeline.scala','val fixture = 1'),('analysis.ipynb',notebook),('README.md','Fictional project overview'),('.aws/credentials','secret'),('../escape.py','never write'),('data.bin',b'\x00'),('nested.zip',b'not opened')])
    response=client.post('/api/project-sources/upload-preview',files=[('files',('project.zip',raw,'application/zip'))],data={'experience_id':record['id']})
    assert response.status_code==200,response.text
    source=response.json();files=source['data']['available_files'];assert len(files)==4
    assert any('Saved output (not rerun)' in f['text'] for f in files)
    assert all(f['archive']=='project.zip' and f['original_sha256'] for f in files)
    assert len(source['data']['excluded'])==4 and not db.list_entities(user,'project_snapshot')
    remote=db.save(user,'project_source',{'provider':'github','label':'example/demo','repo':'example/demo','url':'https://github.com/example/demo','urls':['https://github.com/example/demo'],'commit':'abc123','available_files':[{'file_path':'README.md','sha':'blob-sha','size':40,'suggested':True}],'excluded':[]})
    refs=['https://github.com/example/demo','https://console.aws.amazon.com/s3/home']
    combined=client.post('/api/project-sources/combine',json={'source_ids':[source['id'],remote['id']],'urls':refs,'experience_id':record['id']}).json()
    paths=[f['file_path'] for f in combined['data']['available_files'] if f['file_path'].endswith('collect.py') or f['file_path']=='README.md']
    async def github(path):
        assert path=='repos/example/demo/git/blobs/blob-sha'
        import base64
        return {'encoding':'base64','content':base64.b64encode(b'Fictional remote README').decode()}
    monkeypatch.setattr(sources,'github',github)
    snapshot=client.post('/api/project-sources/'+combined['id']+'/select',json={'file_paths':paths,'experience_id':record['id']})
    assert snapshot.status_code==200,snapshot.text
    data=snapshot.json()['data'];assert len(data['files'])==2 and data['urls']==refs and not data['excluded']
    assert data['files'][0]['archive']=='project.zip'
    remote_file=next(f for f in data['files'] if f['file_path']=='README.md');assert remote_file['url']=='https://github.com/example/demo/blob/abc123/README.md'
    assert not db.list_entities(user,'project_analysis') and db.get(user,record['id'],'experience')['data']==record['data']
    assert request_limit('/api/project-sources/upload-preview')==33*1024*1024


def test_zip_unsafe_paths_symlinks_nested_archives_credentials_and_empty_files_are_excluded(client,account):
    symlink=zipfile.ZipInfo('link.py');symlink.create_system=3;symlink.external_attr=(stat.S_IFLNK|0o777)<<16
    raw=archive([('good.py','print("fixture")'),('/absolute.py','bad'),('C:\\absolute.py','bad'),('folder\\..\\escape.py','bad'),(symlink,'/etc/passwd'),('empty.txt',''),('key.py','aws_secret_access_key = "fictionalSecretLongEnough"'),('id.py','AKIA'+'A'*16),('key.pem','-----BEGIN '+'PRIVATE KEY-----'),('nested.zip',b'bad'),('node_modules/x.js','ignored')])
    result=uploads.preview(account['id'],[('archive.zip',raw)])['data']
    assert [f['file_path'] for f in result['available_files']]==['archive.zip/good.py']
    assert len(result['excluded'])==10


def test_zip_duplicate_paths_and_multiple_archives_stay_distinct(account):
    first=archive([('main.py','print(1)'),('main.py','print(2)')]);second=archive([('main.py','print(3)')])
    result=uploads.preview(account['id'],[('one.zip',first),('two.zip',second),('notes.txt',b'notes')])['data']
    assert [f['file_path'] for f in result['available_files']]==['one.zip/main.py','two.zip/main.py','notes.txt']
    assert len(result['excluded'])==1


def test_zip_limits_corruption_and_selection_are_enforced(client,account,monkeypatch):
    user=account['id']
    for raw in [b'not a zip',archive([('main.py','hello')])[:20]]:
        with pytest.raises(HTTPException) as error:uploads.preview(user,[('broken.zip',raw)])
        assert error.value.status_code==400
    monkeypatch.setattr(uploads,'MAX_EXPANDED',8)
    with pytest.raises(HTTPException) as error:uploads.preview(user,[('large.zip',archive([('x.py','a'*9)]))])
    assert error.value.status_code==413
    monkeypatch.setattr(uploads,'MAX_EXPANDED',64*1024*1024)
    with pytest.raises(HTTPException):uploads.preview(user,[('many.zip',archive([(str(i)+'.py','x') for i in range(1001)]))])
    result=uploads.preview(user,[('ratio.zip',archive([('safe.py','print(1)'),('compressed.txt','a'*(1024*1024+1))]))])['data']
    assert len(result['available_files'])==1 and 'compression ratio' in result['excluded'][0]['reason']
    source=uploads.preview(user,[('main.py',b'print(1)')]);path=source['data']['available_files'][0]['file_path']
    for paths in [[path,path],['other.py']]:
        with pytest.raises(HTTPException):asyncio.run(sources.select(user,source['id'],paths))
    assert client.post('/api/project-sources/upload-preview',files=[('files',('x.py','x','text/plain'))]*31).status_code==400


def test_preview_text_budget_and_file_selection_limit(account,monkeypatch):
    monkeypatch.setattr(sources,'MAX_TOTAL',10)
    row=uploads.preview(account['id'],[('a.txt',b'123456'),('b.txt',b'789012')])
    assert len(row['data']['available_files'])==1 and '2 MB' in row['data']['excluded'][0]['reason']
    monkeypatch.setattr(sources,'MAX_TOTAL',2*1024*1024)
    row=uploads.preview(account['id'],[('many.zip',archive([(str(i)+'.py','x') for i in range(35)]))])
    assert len(row['data']['available_files'])==35
    with pytest.raises(HTTPException):asyncio.run(sources.select(account['id'],row['id'],[f['file_path'] for f in row['data']['available_files']]))


def test_combined_upload_ownership_reference_links_and_backup_roundtrip(client,account,monkeypatch):
    user=account['id']
    with db.connect() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,?)',('another-user','fictional-foreign','unused','{}',db.now()))
    foreign=uploads.preview('another-user',[('private.txt',b'foreign project')]);owned=uploads.preview(user,[('owned.txt',b'owned project')])
    with pytest.raises(HTTPException) as error:uploads.combine(user,[owned['id'],foreign['id']],[])
    assert error.value.status_code==404
    with pytest.raises(HTTPException):asyncio.run(sources.select(user,foreign['id'],['private.txt']))
    for url in ['https://user:secret@example.org/x','file:///etc/passwd','https://example.org:invalid/private']:
        with pytest.raises(HTTPException):uploads.combine(user,[owned['id']],[url])
    combined=uploads.combine(user,[owned['id']],['https://example.org/project'])
    snap=asyncio.run(sources.select(user,combined['id'],['owned.txt']))
    exported=client.get('/api/account/export');assert exported.status_code==200
    # Existing ordinary backups include the preview source and immutable selected snapshot.
    backup=exported.json();wire=json.dumps(backup)
    assert 'owned project' in wire and 'foreign project' not in wire
    assert snap['id'] in wire and combined['id'] in wire

    restored=client.post('/api/account/import',files={'file':('backup.json',exported.content,'application/json')})
    assert restored.status_code==200,restored.text
    copies=[r for r in db.list_entities(user,'project_source') if r['id']!=combined['id'] and r['data'].get('provider')=='mixed']
    assert len(copies)==1 and copies[0]['data']['available_files'][0]['text']=='owned project'
    restored_snap=next(r for r in db.list_entities(user,'project_snapshot') if r['id']!=snap['id'])
    assert restored_snap['data']['source_id']==copies[0]['id']
    assert restored_snap['data']['urls']==['https://example.org/project']


def test_existing_individual_uploads_can_be_combined_with_new_zips(client,account):
    original=client.post('/api/project-sources/upload',files=[('files',('old.py','print("older upload")','text/plain'))]).json()
    uploaded=uploads.preview(account['id'],[('new.zip',archive([('new.py','print("new file")')]))])
    combined=uploads.combine(account['id'],[original['data']['source_id'],uploaded['id']],[])
    files=combined['data']['available_files'];assert {f['file_path'] for f in files}=={'old.py','new.zip/new.py'}
    assert uploads.combine(account['id'],[original['data']['source_id'],uploaded['id']],[])['id']==combined['id']
    selected=asyncio.run(sources.select(account['id'],combined['id'],[f['file_path'] for f in files]))
    assert len(selected['data']['files'])==2 and db.get(account['id'],original['id'],'project_snapshot')['data']==original['data']


def test_encrypted_unsupported_and_corrupt_members_are_excluded(account):
    import struct
    # Mark the second central-directory record encrypted; no encrypted content is opened.
    raw=bytearray(archive([('good.py','fixture'),('encrypted.py','not opened')],zipfile.ZIP_STORED))
    first=raw.index(b'PK\x01\x02');second=raw.index(b'PK\x01\x02',first+4)
    struct.pack_into('<H',raw,second+8,1)
    data=uploads.preview(account['id'],[('encrypted.zip',bytes(raw))])['data']
    assert len(data['available_files'])==1 and 'Encrypted' in data['excluded'][0]['reason']
    raw=archive([('good.py','fixture')],zipfile.ZIP_BZIP2)
    with pytest.raises(HTTPException):uploads.preview(account['id'],[('unsupported.zip',raw)])
    raw=bytearray(archive([('good.py','fixture'),('bad.py','bad checksum')],zipfile.ZIP_STORED))
    first=raw.index(b'PK\x01\x02');second=raw.index(b'PK\x01\x02',first+4);raw[second+16]^=1
    data=uploads.preview(account['id'],[('corrupt.zip',bytes(raw))])['data']
    assert len(data['available_files'])==1 and 'could not be read' in data['excluded'][0]['reason']
