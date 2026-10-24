from app import ai, documents, resume_data
from app.models import ExperienceItem
from pydantic import ValidationError
import pytest


def test_skill_levels_survive_save_and_backup_without_changing_legacy(client,account):
    legacy=client.post('/api/experience',json={'category':'skills','title':'Programming','tools':'Python, SQL','confirmed':True}).json()
    assert legacy['data']['skill_items']==[]
    body={**legacy['data'],'skill_items':[{'name':'Python','level':'beginner'},{'name':'SQL','level':'intermediate'},{'name':'Git','level':'unknown'}],'tools':'Python, SQL, Git'}
    updated=client.put('/api/experience/'+legacy['id'],json=body)
    assert updated.status_code==200,updated.text
    assert updated.json()['data']['skill_items']==body['skill_items']
    assert 'intermediate' in ai.experience_text(updated.json()['data'])
    backup=client.get('/api/account/export')
    assert backup.status_code==200
    assert 'intermediate' in backup.text and 'Python' in backup.text


def test_skill_exports_label_self_ratings_and_omit_unknown():
    entry=ExperienceItem(category='skills',title='Programming',skill_items=[{'name':'Python','level':'advanced'},{'name':'Git'}]).model_dump()
    snapshot=resume_data.entry_snapshot(entry,'example')
    data={'name':'Fictional Student','sections':[{'title':'Skills','entries':[snapshot]}]}
    text=documents.resume_plain(data)
    assert 'Python (advanced, self-rated)' in text
    assert 'Git' in text and 'unknown' not in text
    assert 'Skills:' in text
    assert 'unknown' in ai.experience_text(entry)
    with pytest.raises(ValidationError):
        ExperienceItem(category='skills',title='Skill',skill_items=[{'name':'SQL','level':'expert-certified'}])


def test_dates_keep_precision_and_preserve_old_snapshots():
    old={'category':'employment','title':'Intern','dates':'Summer 2025'}
    assert resume_data.record_dates(old)=='Summer 2025'
    assert resume_data.record_dates({**old,'start_date':'June 2025','end_date':'August 2025'})=='June 2025 – August 2025'
    assert resume_data.record_dates({**old,'start_date':'June 5, 2025','end_date':'Present'})=='June 5, 2025 – Present'
