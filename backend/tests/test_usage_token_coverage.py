import io,json
from app import cost_history as costs,db,interview_audio as audio

def event(user,key,**values):
 return costs.write(user,{'event_key':key,'occurred_at':'2026-10-23T20:00:00+00:00','model':'fictional','process':'interview_practice','status':'completed',**values})

def test_reported_tokens_and_missing_prices_are_independent(client,account):
 u=account['id'];e=event(u,'complete')
 response={'usage':{'input_tokens':100,'output_tokens':40,'input_tokens_details':{'cached_tokens':20},'output_tokens_details':{'reasoning_tokens':10}}}
 costs.finish(u,e,{'model':'unpriced-fictional'},response)
 r=costs.report(u);v=r['series'][0]
 assert v['input_tokens']==100 and v['output_tokens']==40 and v['cached_input_tokens']==20 and v['reasoning_tokens']==10
 assert v['token_requests_reported']==1 and v['token_requests_missing']==0 and v['unpriced_requests']==1
 assert v['cached_requests_missing']==v['reasoning_requests_missing']==0
 assert v['input_tokens']+v['output_tokens']==140 # Included subtotals never add twice.

def test_duration_and_historical_audio_counts_are_unknown_without_rewriting(client,account):
 u=account['id'];e=audio.begin(u,audio.TRANSCRIBE,'interview_transcription','Duration only')
 audio.finish(u,e,{'usage':{'type':'duration','seconds':30}},'completed',audio.TRANSCRIBE)
 old=event(u,'legacy-audio',process='interview_delivery',usage_reported=True,input_tokens=50,output_tokens=5,estimated_cost_usd=.02)
 ordinary=event(u,'legacy-text',usage_reported=True,input_tokens=20,output_tokens=7,cached_input_tokens=3)
 with db.connect() as c:
  for id in (old['id'],ordinary['id']):
   row=c.execute('SELECT payload FROM entities WHERE id=?',(id,)).fetchone();value=json.loads(row['payload'])
   for k in ('token_counts_reported','cached_counts_reported','reasoning_counts_reported'):value.pop(k,None)
   c.execute('UPDATE entities SET payload=? WHERE id=?',(json.dumps(value),id))
 before={r['id']:r['data'] for r in db.list_entities(u,'usage_event')}
 result=costs.report(u);assert result['totals']['token_requests_missing']==2 and result['totals']['token_requests_reported']==1
 assert result['totals']['input_tokens']==70 and result['totals']['output_tokens']==12
 assert before=={r['id']:r['data'] for r in db.list_entities(u,'usage_event')}
 assert db.get(u,e['id'],'usage_event')['data']['token_counts_reported'] is False

def test_audio_token_splits_and_subtotals_are_retained(client,account):
 u=account['id'];e=audio.begin(u,audio.DELIVERY,'interview_delivery','Audio tokens')
 audio.finish(u,e,{'usage':{'prompt_tokens':120,'completion_tokens':60,'prompt_tokens_details':{'audio_tokens':90,'cached_tokens':10},'completion_tokens_details':{'audio_tokens':0,'reasoning_tokens':5}}},'completed',audio.DELIVERY)
 value=db.get(u,e['id'],'usage_event')['data'];assert value['token_counts_reported'] and value['cached_counts_reported'] and value['reasoning_counts_reported']
 assert value['cached_input_tokens']==10 and value['reasoning_tokens']==5
 result=costs.report(u)['totals'];assert result['input_tokens']+result['output_tokens']==180 and result['token_requests_missing']==0

def test_audio_standard_details_match_presence_metadata(client,account):
 u=account['id'];e=audio.begin(u,audio.TRANSCRIBE,'interview_transcription','Token details')
 audio.finish(u,e,{'usage':{'input_tokens':100,'output_tokens':20,'input_tokens_details':{'cached_tokens':8},'output_tokens_details':{'reasoning_tokens':3}}},'completed',audio.TRANSCRIBE)
 value=db.get(u,e['id'],'usage_event')['data']
 assert value['cached_counts_reported'] and value['cached_input_tokens']==8
 assert value['reasoning_counts_reported'] and value['reasoning_tokens']==3

def test_week_month_filters_and_exports_preserve_totals_and_coverage(client,account):
 u=account['id'];event(u,'known',usage_reported=True,token_counts_reported=True,input_tokens=30,output_tokens=5,estimated_cost_usd=.01)
 event(u,'missing',token_counts_reported=False,estimated_cost_usd=None,partial=True)
 day=costs.report(u,start='2026-10-21',end='2026-10-27',tz='America/Phoenix')
 for bucket in ('week','month'):
  result=costs.report(u,start='2026-10-21',end='2026-10-27',tz='America/Phoenix',bucket=bucket)
  assert result['totals']==day['totals'] and result['series'][0]['token_requests_missing']==1
 empty=costs.report(u,start='2026-09-01',end='2026-09-02')['totals'];assert empty['requests']==0 and empty['token_requests_missing']==0
 exported=client.get('/api/account/export').json()
 r=client.post('/api/account/import',files={'file':('backup.json',json.dumps(exported).encode(),'application/json')});assert r.status_code==200,r.text
 assert costs.report(u)['totals']==day['totals'] # Usage event deduplication preserves counts.

def test_flags_reject_bool_counts_and_distinguish_missing_subtypes():
 assert costs.token_flags({'input_tokens':True,'output_tokens':2})['token_counts_reported'] is False
 flags=costs.token_flags({'input_tokens':5,'output_tokens':4,'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}})
 assert all(flags.values())
 flags=costs.token_flags({'input_tokens':5,'output_tokens':4});assert flags['token_counts_reported'] and not flags['cached_counts_reported'] and not flags['reasoning_counts_reported']
