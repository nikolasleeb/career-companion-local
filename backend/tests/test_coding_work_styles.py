"""Coding never receives optional Work Styles, including legacy enabled sessions."""
import json
from app import db,work_preferences
from test_interview_practice import create,load,body,wait,model


def preferences(user):
 return db.save(user,'work_preferences',{'revision':1,'summary':'I prefer written instructions and time to prepare.','preferences':[],'reviewed':True,'use_for_ai':True,'coach_report_access':False},work_preferences.identity(user))


def test_coding_context_excludes_legacy_enabled_summary_without_rewriting_saved_data(client,account,model):
 prefs=preferences(account['id']);s=create(client,kind='coding')
 s=db.save(account['id'],'interview_session',{**s['data'],'use_work_styles':True},s['id'])
 before=load(client,s['id']);assert before['work_styles_available'] is False
 result=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s)))
 assert result['status']=='completed',result
 assert 'I prefer written instructions' not in json.dumps(model[-1][1])
 assert not any(r['kind']=='work_summary' for r in model[-1][1]['source_catalog'])
 assert db.get(account['id'],s['id'])['data']['use_work_styles'] is True
 assert db.get(account['id'],prefs['id'])==prefs


def test_coding_cannot_enable_work_styles_but_other_interviews_retain_consent(client,account,model):
 prefs=preferences(account['id']);s=create(client,kind='coding')
 assert client.post('/api/interview-practice/sessions',json={'kind':'coding','use_work_styles':True}).status_code==422
 assert client.patch('/api/interview-practice/sessions/'+s['id']+'/context',json={'expected_updated_at':s['updated_at'],'use_work_styles':True}).status_code==422
 behavioral=create(client,kind='behavioral',use_work_styles=True)
 assert load(client,behavioral['id'])['work_styles_available'] is True
 result=wait(client,client.post('/api/interview-practice/sessions/'+behavioral['id']+'/actions',json=body(behavioral)))
 assert result['status']=='completed',result
 assert any(r['kind']=='work_summary' for r in model[-1][1]['source_catalog'])
 assert db.get(account['id'],prefs['id'])==prefs
