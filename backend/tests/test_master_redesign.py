import copy
import io
import json
import re
import pytest
from docx import Document
from pypdf import PdfReader
from app import ai, db, resume_data
from app.models import SettingsUpdate
from app.network import ServiceError


def add(client, **data):
    response=client.post('/api/experience',json={'confirmed':True,**data})
    assert response.status_code==200,response.text
    return response.json()


def test_project_links_preserve_legacy_primary_and_additional_sources(client,account):
    from app.models import ExperienceItem
    links=['https://github.com/example/base','https://github.com/example/extension']
    old=add(client,category='project',title='Course project',project_url=links[0])
    assert old['data']['project_urls']==links[:1]
    updated=client.put('/api/experience/'+old['id'],json={**old['data'],'project_urls':links}).json()
    assert updated['data']['project_url']==links[0] and updated['data']['project_urls']==links
    assert ExperienceItem(title='P',project_url=links[0],project_urls=[links[0]+'/']).project_urls==links[:1]
    for bad in ['javascript:alert(1)','file:///tmp/certificate','https://user:secret@example.com','https://example.com/'+'x'*2000]:
        assert client.put('/api/experience/'+old['id'],json={**updated['data'],'project_urls':[links[0],bad]}).status_code==422
    cleared=client.put('/api/experience/'+old['id'],json={**updated['data'],'project_url':'','project_urls':[]}).json()
    assert cleared['data']['project_url']=='' and cleared['data']['project_urls']==[]
    from app import ai
    assert all(link in ai.experience_text(updated['data']) for link in links)
    assert all(any(link in bullet for bullet in resume_data.entry_snapshot(updated['data'],old['id'])['bullets']) for link in links)


def test_structured_student_records_and_exports(client,account):
    profile={'name':'Fictional Student','email':'student@example.com','phone':'+1 520 555 0100','city':'Tucson','state':'AZ','country':'United States','county':'Pima','website':'https://example.com/portfolio','linkedin':'https://www.linkedin.com/in/fictional-student'}
    assert client.put('/api/settings',json=profile).status_code==200
    first=add(client,category='education',title='BS Information Science',organization='Example University',degree='BS',major='Information Science',minor='Statistics',concentration='Data analytics',location='Tucson, AZ',start_date='August 2024',expected_graduation='May 2028',gpa='3.8',gpa_scale='4.0',honors='Fictional honors program',relevant_courses='Database systems; Data visualization',description='Course labs, not professional employment.')
    second=add(client,category='education',title='Associate degree',organization='Example College',degree='Associate degree',end_date='May 2024')
    job=add(client,category='employment',title='Student assistant',organization='Example library',location='Tucson, AZ',work_arrangement='hybrid',start_date='2025',end_date='Present',description='Responded to student questions.',accomplishments='Created a reference checklist.',tools='Excel')
    project=add(client,category='project',title='Campus dashboard',organization='Information science course',description='Built a class dashboard.',contribution='I created the charts; teammates collected the data.',project_url='https://example.com/dashboard',tools='SQL')
    ids=[r['id'] for r in [first,second,job,project]]
    for template in ('education','experience'):
        client.put('/api/settings',json=profile)
        client.put('/api/experience/'+first['id'],json=first['data'])
        response=client.post('/api/resumes',json={'experience_ids':ids,'template':template})
        assert response.status_code==200,response.text
        version=response.json();data=version['data']
        assert data['profile']['phone']==profile['phone']
        assert len(next(s for s in data['sections'] if s['title']=='Education')['entries'])==2
        assert data['contact_lines'][0]=='student@example.com | +1 520 555 0100 | Tucson, Pima, AZ, United States'
        for format in ('txt','docx','pdf'):
            raw=client.get('/api/resumes/'+version['id']+'/export/'+format).content
            if format=='docx': text='\n'.join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
            elif format=='pdf': text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
            else: text=raw.decode()
            text=re.sub(r'\s+',' ',text)
            for expected in ('3.8 / 4.0','Fictional honors program','Database systems','Data visualization','Tucson, AZ','Hybrid','Created a reference checklist.','I created the charts','https://example.com/dashboard','https://example.com/portfolio','https://www.linkedin.com/in/fictional-student','Expected graduation May 2028','Statistics'):
                assert expected in text,(format,expected)
        saved=copy.deepcopy(data)
        client.put('/api/settings',json={'city':'Phoenix'})
        client.put('/api/experience/'+first['id'],json={**first['data'],'gpa':'3.9'})
        assert next(r for r in client.get('/api/workspace').json()['resume'] if r['id']==version['id'])['data']==saved
    assert not project['data']['location']
    assert not project['data']['dates']


def test_legacy_contact_and_education_are_not_guessed(client,account):
    line='Student | email@example.com | old website text'
    client.put('/api/settings',json={'name':'Student','contact':line})
    old=add(client,category='education',title='Old freeform degree',organization='Old college',dates='Expected May 2027',description='Original coursework notes.')
    first=client.post('/api/resumes',json={'experience_ids':[old['id']]}).json()
    assert first['data']['contact']==line
    assert first['data']['sections'][0]['entries'][0]['title']=='Old freeform degree'
    client.put('/api/settings',json={'email':'email@example.com','contact_reviewed':True})
    second=client.post('/api/resumes',json={'experience_ids':[old['id']]}).json()
    assert second['data']['contact']=='email@example.com'
    assert client.get('/api/me').json()['settings']['contact']==line
    assert first['data']['contact']==line
    assert db.list_entities(account['id'],'experience')[0]['data']['description']=='Original coursework notes.'


def test_structured_backup_and_old_backup_import(client,account):
    profile={'name':'Sample','email':'sample@example.com','city':'Tucson','country':'US','website':'https://example.com','contact_reviewed':True}
    client.put('/api/settings',json=profile)
    item=add(client,category='education',title='Degree',degree='BS',gpa='3.6',gpa_scale='4.0',relevant_courses='SQL')
    backup=client.get('/api/account/export').json()
    assert backup['profile']['email']==profile['email']
    assert backup['profile']['contact_reviewed'] is True
    client.put('/api/settings',json={'city':'Changed'})
    response=client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')})
    assert response.status_code==200,response.text
    assert client.get('/api/me').json()['settings']['city']=='Tucson'
    records=client.get('/api/workspace').json()['experience']
    assert len(records)==2 and records[0]['id']!=records[1]['id']
    assert all(r['data']['gpa']=='3.6' for r in records)
    old={'schema_version':1,'profile':{'name':'Old profile','contact':'Legacy contact','mode':'economy'},'records':[{'id':'old-record','kind':'experience','data':{'category':'education','title':'Old degree','description':'Unchanged notes','confirmed':True}}],'files':{}}
    assert client.post('/api/account/import',files={'file':('old.json',json.dumps(old).encode(),'application/json')}).status_code==200
    assert client.get('/api/me').json()['settings']['contact']=='Legacy contact'
    assert client.get('/api/me').json()['settings']['contact_reviewed'] is False


def test_structured_evidence_and_numeric_guard(client,account):
    item=add(client,category='education',title='BS',degree='BS',gpa='3.8',gpa_scale='4.0',relevant_courses='SQL database systems',description='Completed database coursework.')
    retrieved=db.retrieve(account['id'],'SQL GPA')
    assert item['id'] in [r['id'] for r in retrieved]
    assert ai.valid_quote('SQL database systems',ai.experience_text(item['data']))
    assert ai.valid_quote('3.8',ai.experience_text(item['data']))
    guide={'id':'g','kind':'guidance','data':{'text':'Keep facts accurate.'}}
    output={'requirements':[{'keyword':'SQL','job_quote':'Use SQL','status':'supported','evidence':[{'record_id':item['id'],'quote':'SQL database systems'}]}],'suggestions':[]}
    ai.validate_analysis(output,{'description':'Use SQL'},retrieved+[guide])
    output['suggestions']=[{'record_id':item['id'],'original':'Completed database coursework.','proposed':'Earned a 4.9 GPA.','guide_id':'g','guide_quote':'Keep facts accurate.'}]
    with pytest.raises(ServiceError,match='unsupported number'): ai.validate_analysis(output,{'description':'Use SQL'},retrieved+[guide])
    output['suggestions'][0].update(original='3.8',proposed='3.8')
    with pytest.raises(ServiceError,match='structured facts'): ai.validate_analysis(output,{'description':'Use SQL'},retrieved+[guide])


@pytest.mark.parametrize('field,value',[('website','javascript:alert(1)'),('linkedin','https://user:password@example.com'),('project_url','file:///tmp/private')])
def test_resume_links_are_validated(client,account,field,value):
    response=client.post('/api/experience',json={'title':'Project',field:value}) if field=='project_url' else client.put('/api/settings',json={field:value})
    assert response.status_code==422


def test_optional_details_do_not_invent_values():
    entry=resume_data.entry_snapshot({'category':'education','title':'Education','gpa':'3.7','gpa_scale':'','expected_graduation':'[date missing]','honors':'[missing honors]'},'test')
    assert entry['bullets']==['GPA: 3.7']
    assert not entry['dates']
    assert resume_data.contact_lines({'name':'Only a name'})==[]
