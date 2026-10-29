import json
from app import ai,db,job_ai,resume_data,resume_parser
from app.models import ExperienceItem


def create(client,**changes):
    data={'category':'project','title':'Fictional independent project','description':'Configured a fictional processing workflow.','contribution':'Existing contribution stays verbatim.','individual_project':True,'confirmed':True,**changes}
    result=client.post('/api/experience',json=data)
    assert result.status_code==200,result.text
    return result.json()


def test_individual_project_saves_reopens_and_toggles_without_erasing_content(client,account,monkeypatch):
    async def no_ai(*args,**kwargs):raise AssertionError('Saving project format must not call AI')
    monkeypatch.setattr(ai,'structured',no_ai)
    row=create(client);assert row['data']['individual_project'] is True
    saved=next(r for r in client.get('/api/workspace').json()['experience'] if r['id']==row['id']);assert saved['data']==row['data']
    changed=client.put('/api/experience/'+row['id'],json={**row['data'],'individual_project':False})
    assert changed.status_code==200,changed.text
    assert changed.json()['data']['individual_project'] is False
    for key in ('description','contribution','title','confirmed'):assert changed.json()['data'][key]==row['data'][key]


def test_old_records_default_unchecked_and_only_explicit_project_type_reaches_ai(account):
    old={'category':'project','title':'Older project','description':'Existing content','confirmed':True}
    assert ExperienceItem.model_validate(old).individual_project is False
    assert 'project_type' not in ai.experience_fields(old)
    assert 'project_type' not in ai.experience_fields({**old,'individual_project':False})
    assert ai.experience_fields({**old,'individual_project':True})['project_type']=='Individual project'
    assert 'project_type' not in ai.experience_fields({**old,'category':'employment','individual_project':True})
    # An unknown/unchecked source designation does not manufacture a duplicate project.
    assert resume_parser.fingerprint(old)==resume_parser.fingerprint({**old,'individual_project':True})


def test_drafts_are_excluded_and_reviewed_solo_format_reaches_coach_context(client,account):
    row=create(client,confirmed=False);user=account['id']
    assert not any(r['record_id']==row['id'] for r in job_ai.profile(user)['sources'])
    response=client.put('/api/experience/'+row['id'],json={**row['data'],'confirmed':True});assert response.status_code==200
    source=next(r for r in job_ai.profile(user)['sources'] if r['record_id']==row['id'] and r['field']=='individual_project')
    assert source['text']=='Individual project'
    snap=resume_data.entry_snapshot(response.json()['data'],row['id'])
    assert snap['individual_project'] is True and 'Individual project' not in snap['bullets']
    assert 'Existing contribution stays verbatim.' in snap['bullets']


def test_backup_roundtrip_keeps_project_type_and_older_records(client,account):
    row=create(client)
    older=db.save(account['id'],'experience',{'category':'project','title':'Legacy project','description':'Legacy details','confirmed':True})
    exported=client.get('/api/account/export');assert exported.status_code==200
    response=client.post('/api/account/import',files={'file':('backup.json',exported.content,'application/json')});assert response.status_code==200,response.text
    copies=[r for r in db.list_entities(account['id'],'experience') if r['id']!=row['id'] and r['data'].get('title')==row['data']['title']]
    assert len(copies)==1 and copies[0]['data']['individual_project'] is True and copies[0]['data']['contribution']==row['data']['contribution']
    assert 'individual_project' not in db.get(account['id'],older['id'],'experience')['data']
    assert all(not r['data'].get('individual_project',False) for r in db.list_entities(account['id'],'experience') if r['data']['title']=='Legacy project')


def test_project_format_changes_cannot_edit_another_accounts_record(client,account):
    row=create(client)
    other=client.post('/api/auth/register',json={'username':'foreign-project-owner','password':'fictional-test-password'}).json();assert other['id']!=account['id']
    client.headers['X-CSRF-Token']=other['csrf']
    response=client.put('/api/experience/'+row['id'],json={**row['data'],'individual_project':False});assert response.status_code==404
    assert db.get(account['id'],row['id'],'experience')['data']['individual_project'] is True
