import asyncio,json
from app import ai,db,work_style_summary as summary,work_preferences


def result(user):
 return db.save(user,'work_style',{'status':'completed','completed_at':db.now(),'answers':{'private-item':'RAW_PRIVATE_RESPONSE'},'report':{'domains':[{'name':'Conscientiousness','mean':4.6,'pattern':'A more organized and persistent self-description.','potential':'Planning and completion routines may feel natural.','friction':'Polishing may continue after a result is good enough.','environment':'Clear acceptance criteria and sustainable deadlines.'},{'name':'Extraversion','mean':2.8,'pattern':'A mix of reserved and outwardly engaged interaction styles.','environment':'Focused work with agreed discussion points.'}],'facets':[{'name':'Sensitive private facet','pattern':'PRIVATE_FACET_DETAILS'}],'preferences':[]}})


def test_completed_results_support_synthesis_without_work_comparisons(client,account,monkeypatch):
 user=account['id'];assessment=result(user);calls=[]
 async def model(schema,payload,*args,**kwargs):
  calls.append((payload,kwargs));text=json.dumps(payload)
  assert 'result:C' in text and '4.60' in text and 'result:E' in text
  assert 'RAW_PRIVATE_RESPONSE' not in text and 'PRIVATE_FACET_DETAILS' not in text
  instructions=kwargs['instructions'];assert 'Synthesize' in instructions and 'second person' in instructions and 'MAY' in instructions and 'Do not rewrite each answer' in instructions
  source=payload['source_statements'][0]
  return {'summary':'You may work best with clear goals and room for focused preparation, while using planned conversations to compare ideas. Your results suggest that structure could support your follow-through, although agreeing on a stopping point may help keep polishing proportionate.','references':[{'source_id':source['id'],'quote':'A more organized and persistent self-description.'}]},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 value=asyncio.run(summary.execute(user,summary.Request(expected_revision=0,request_token='fictional-summary-synthesis')))
 assert value['assessment_id']==assessment['id'] and len(calls)==1 and calls[0][1]['retry_allowed'] is False
 assert not work_preferences.read(user)['summary'] and not work_preferences.read(user)['use_for_ai']
 assert value['summary'].startswith('You may') and value['source_snapshot']


def test_reviewed_project_context_requires_explicit_opt_in(client,account):
 user=account['id'];result(user)
 db.save(user,'experience',{'category':'project','title':'Fictional reviewed cluster','description':'Configured a small cluster and iterated on setup checks.','confirmed':True})
 db.save(user,'experience',{'category':'project','title':'UNREVIEWED_PROJECT','confirmed':False})
 plain=summary.payload(user,summary.Request(expected_revision=0,request_token='fictional-plain-summary'))
 contextual=summary.payload(user,summary.Request(expected_revision=0,request_token='fictional-context-summary',include_profile=True))
 assert 'Fictional reviewed cluster' not in json.dumps(plain)
 assert 'Fictional reviewed cluster' in json.dumps(contextual) and 'UNREVIEWED_PROJECT' not in json.dumps(contextual)
 assert contextual['profile_revision'] and any(row.get('kind','').startswith('reviewed work example') for row in contextual['source_statements'])


def test_other_account_results_and_sensitive_domain_values_are_excluded(client,account):
 other=client.post('/api/auth/register',json={'username':'other-report-owner','password':'fictional-test-password'}).json()
 result(other['id']);request=summary.Request(expected_revision=0,request_token='fictional-owner-summary',notes='I like planning a practical first step.')
 payload=summary.payload(account['id'],request);assert not any(row['id'].startswith('result:') for row in payload['source_statements'])
 record=result(account['id']);record['data']['report']['domains'][0]['friction']='mental health PRIVATE_DETAILS'
 db.save(account['id'],'work_style',record['data'],record['id'])
 payload=summary.payload(account['id'],request);assert 'PRIVATE_DETAILS' not in json.dumps(payload)
