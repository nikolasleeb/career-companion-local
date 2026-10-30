"""A hidden coding setting cannot turn a case/presentation into a SQL exercise."""
import pytest
from app import db,interview_practice as practice
from test_interview_practice import create,load,question,body,wait,model

@pytest.mark.parametrize('kind',['behavioral','star','case','domain','presentation','other'])
@pytest.mark.parametrize('operation',['question','guide','review'])
def test_non_coding_requests_ignore_legacy_sql_and_difficulty_but_keep_relevant_context(client,account,model,kind,operation):
 db.save(account['id'],'experience',{'category':'project','title':'Fictional SQL reporting project','description':'Explained reporting findings to stakeholders.','confirmed':True})
 s=create(client,kind=kind,language='SQL',difficulty='advanced',company='Fictional Bank',role='Operations analyst',notes='Explain decisions to a nontechnical audience.')
 d=question(client,s);q=d['questions'][0]
 result=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(d['session'],operation,question_id=q['id'],answer='I explained findings and compared the options.' if operation=='review' else '')))
 assert result['status']=='completed',result
 sent=model[-1][1]
 assert 'language' not in sent and 'difficulty' not in sent
 assert sent['practice_kind']==kind and sent['company']=='Fictional Bank' and sent['role']=='Operations analyst'
 assert sent['notes']=='Explain decisions to a nontechnical audience.'
 assert any('Fictional SQL reporting project' in r['text'] for r in sent['source_catalog'])
 if operation=='question':
  assert '1–3 consistent input/output examples' not in sent['task']
  if kind=='case':assert 'BUSINESS CASE' in sent['task'] and 'write queries' in sent['task']
  if kind=='presentation':assert 'PRESENTATION OR PORTFOLIO' in sent['task'] and 'write queries' in sent['task']
 # No migration or rewriting of old stored settings is required.
 assert load(client,s['id'])['session']['data']['language']=='SQL'


def test_coding_keeps_explicit_sql_language_difficulty_and_coding_task(client,account,model):
 s=create(client,kind='coding',language='SQL',difficulty='advanced')
 result=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,focus='Selecting, sorting and ordering')))
 assert result['status']=='completed',result
 sent=model[-1][1]
 assert sent['language']=='SQL' and sent['difficulty']=='advanced'
 assert sent['focus']=='Selecting, sorting and ordering'
 assert '1–3 consistent input/output examples' in sent['task'] and 'BUSINESS CASE' not in sent['task']


def test_non_coding_explicit_sql_focus_remains_an_explicit_user_request(client,account,model):
 s=create(client,kind='case',language='SQL');focus='Discuss a SQL reporting outage as a business case; no query writing.'
 result=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,focus=focus)))
 assert result['status']=='completed',result
 assert model[-1][1]['focus']==focus and 'language' not in model[-1][1]
