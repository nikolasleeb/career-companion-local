import asyncio,io,json,math,struct,time,wave
import pytest
from app import db,ai,credentials,interview_audio as audio,interview_practice as practice,work_preferences,work_style_summary as summary,cost_history
from test_interview_practice import create,question,body,wait,load

def wav(seconds=1):
 out=io.BytesIO()
 with wave.open(out,'wb') as f:
  f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b''.join(struct.pack('<h',int(math.sin(i*.2)*10000)) for i in range(int(24000*seconds))))
 return out.getvalue()
def ready(client,account):
 credentials.save(account['id'],'sk-fictional-voice');s=create(client);d=question(client,s);return d['session'],d['questions'][0]
def start(client,s,q,token=None,raw=None):
 return client.post('/api/interview-practice/sessions/'+s['id']+'/voice',params={'question_id':q['id'],'request_token':token or 'fictional-'+db.uid()},content=raw or wav(),headers={'Content-Type':'audio/wav'})
def delivery():return {'audibility':'Clearly audible.','pacing':'Some pauses between points.','vocal_delivery':'Volume stayed consistent.','suggestions':['Pause between examples.']}

@pytest.fixture
def providers(monkeypatch):
 calls=[];buffers=[]
 async def provider(user,model,raw):
  calls.append(model);buffers.append(raw)
  return {'text':'I built a scheduling tool and checked it with my team.'} if model==audio.TRANSCRIBE else {'choices':[{'message':{'content':json.dumps(delivery())}}]}
 monkeypatch.setattr(audio,'provider',provider);return calls,buffers

def test_voice_bounds_partial_results_and_no_audio_persistence(client,account,providers):
 s,q=ready(client,account);token='fictional-'+db.uid();r=start(client,s,q,token);result=wait(client,r);assert result['status']=='completed',result
 rows=client.get('/api/interview-practice/sessions/'+s['id']+'/voice').json();v=rows[0]
 assert v['data']['transcript'].startswith('I built') and v['data']['delivery']['audibility']=='Clearly audible.'
 assert providers[0]==[audio.TRANSCRIBE,audio.DELIVERY] and all(not v for v in providers[1])
 repeated=start(client,s,q,token);assert repeated.json()['task_id']==r.json()['task_id'];assert len(providers[0])==2
 with db.connect() as c:
  text=' '.join(r[0] or '' for r in c.execute('SELECT result FROM tasks'))+' '.join(r[0] for r in c.execute('SELECT payload FROM entities'))
 assert 'RIFF' not in text and 'base64' not in text and 'pcm' not in text
 assert start(client,s,q,raw=b'broken audio').status_code==422
 assert start(client,s,q,raw=wav(.2)).status_code==422
 assert client.post('/api/interview-practice/sessions/'+s['id']+'/voice',params={'question_id':q['id'],'request_token':'fictional-too-large'},content=b'a'*(audio.MAX_BYTES+1),headers={'Content-Type':'audio/wav'}).status_code==413
 old=v['updated_at'];edited=client.put('/api/interview-practice/voice/'+v['id']+'/transcript',json={'expected_updated_at':old,'transcript':'I built a scheduling tool and checked it with my team.','reviewed':True});assert edited.status_code==200
 assert client.put('/api/interview-practice/voice/'+v['id']+'/transcript',json={'expected_updated_at':old,'transcript':'stale','reviewed':True}).status_code==409

def test_partial_transcription_survives_delivery_failure(client,account,monkeypatch):
 s,q=ready(client,account);buffers=[]
 async def provider(user,model,raw):
  buffers.append(raw)
  if model==audio.TRANSCRIBE:return {'text':'A useful original answer about my project.'}
  raise audio.ServiceError('Fictional unavailable model')
 monkeypatch.setattr(audio,'provider',provider)
 result=wait(client,start(client,s,q));assert result['status']=='completed'
 v=client.get('/api/interview-practice/sessions/'+s['id']+'/voice').json()[0]
 assert v['data']['state']=='partial' and v['data']['transcript'] and v['data']['delivery'] is None
 assert all(not b for b in buffers)

def test_voice_review_context_details_and_backup(client,account,providers,monkeypatch):
 s,q=ready(client,account);wait(client,start(client,s,q));v=client.get('/api/interview-practice/sessions/'+s['id']+'/voice').json()[0]
 async def model(schema,payload,*a,**k):
  assert schema==practice.Coaching
  assert 'scheduling tool' in payload['answer']
  return {'summary':'Explain your personal contribution.','strengths':[],'improvements':['Give the dates.'],'profile_connections':[],'claims_to_clarify':['Confirm when this project happened.'],'follow_up':'How did you validate it?','useful_details':[{'title':'Scheduling project','user_quote':'I built a scheduling tool','text':'Built a scheduling tool.'}]},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 # Unreviewed voice cannot become answer evidence.
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'review',question_id=q['id'],voice_id=v['id'])))
 assert r['status']=='failed' and not load(client,s['id'])['attempts']
 r=client.put('/api/interview-practice/voice/'+v['id']+'/transcript',json={'expected_updated_at':v['updated_at'],'transcript':v['data']['transcript'],'reviewed':True});assert r.status_code==200
 r=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'review',question_id=q['id'],voice_id=v['id'])))
 assert r['status']=='completed',r
 attempt=load(client,s['id'])['attempts'][0];assert attempt['data']['delivery'] and attempt['data']['transcript_snapshot']
 b={'expected_updated_at':attempt['updated_at'],'candidate':0,'title':'Scheduling project','text':'Built a scheduling tool.','reviewed':False}
 path='/api/interview-practice/attempts/'+attempt['id']+'/supporting-details'
 assert client.post(path,json=b).status_code==422
 b['reviewed']=True;approved=client.post(path,json=b);assert approved.status_code==200,approved.text
 assert client.post(path,json=b).json()['already_saved']
 export=client.get('/api/account/export');assert export.status_code==200
 assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(export.json()).encode(),'application/json')}).status_code==200
 assert client.delete('/api/interview-practice/sessions/'+s['id']).status_code==200
 assert db.get(account['id'],approved.json()['saved_id'],'profile_answer')
 export=client.get('/api/account/export');assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(export.json()).encode(),'application/json')}).status_code==200

def test_audio_isolation_and_cancel_preserves_completed_text(client,account,providers,monkeypatch):
 s,q=ready(client,account);wait(client,start(client,s,q));v=client.get('/api/interview-practice/sessions/'+s['id']+'/voice').json()[0]
 other=client.post('/api/auth/register',json={'username':'other-voice','password':'fictional-voice-password'}).json();client.headers['X-CSRF-Token']=other['csrf']
 from conftest import onboard_test_account
 onboard_test_account(other)
 assert client.get('/api/interview-practice/sessions/'+s['id']+'/voice').status_code==404
 assert client.put('/api/interview-practice/voice/'+v['id']+'/transcript',json={'expected_updated_at':v['updated_at'],'transcript':'attack','reviewed':True}).status_code==404
 # Direct worker cancellation also clears its mutable buffer.
 raw=bytearray(wav());metrics=audio.wav_info(raw);db.save(account['id'],'interview_voice',{'session_id':s['id'],'question_id':q['id'],'state':'processing','transcript':'','metrics':metrics},'cancel-voice')
 async def slow(user,model,raw):
  if model==audio.TRANSCRIBE:return {'text':'Completed transcript.'}
  raise asyncio.CancelledError()
 monkeypatch.setattr(audio,'provider',slow)
 with pytest.raises(asyncio.CancelledError):asyncio.run(audio.process_audio(account['id'],'cancel-voice',raw,metrics))
 assert not raw and db.get(account['id'],'cancel-voice','interview_voice')['data']['transcript']=='Completed transcript.'

def test_weekly_local_midnight_year_and_partial_range(client,account):
 for i,stamp in enumerate(['2026-12-28T06:30:00+00:00','2026-12-28T07:30:00+00:00','2027-01-04T06:30:00+00:00','2027-01-04T07:30:00+00:00']):
  cost_history.write(account['id'],{'event_key':'week-'+str(i),'occurred_at':stamp,'model':'fictional','process':'interview_transcription','status':'completed','estimated_cost_usd':.1})
 daily=cost_history.report(account['id'],tz='America/Phoenix');weekly=cost_history.report(account['id'],tz='America/Phoenix',bucket='week')
 assert [r['key'] for r in weekly['series']]==['2026-12-21','2026-12-28','2027-01-04']
 assert daily['totals']==weekly['totals']
 partial=cost_history.report(account['id'],start='2026-12-29',end='2027-01-03',tz='America/Phoenix',bucket='week')
 assert partial['totals']['requests']==1 and partial['series'][0]['key']=='2026-12-28'
 assert client.get('/api/usage?bucket=week').status_code==200
 assert client.get('/api/usage?bucket=invalid').status_code==422

def test_summary_profile_opt_in_is_reviewed_and_bounded(client,account):
 u=account['id'];project=db.save(u,'experience',{'category':'project','title':'Scheduling project','description':'Built a scheduling tool with teammates.','confirmed':True})
 db.save(u,'experience',{'category':'project','title':'UNREVIEWED_SECRET','confirmed':False})
 db.save(u,'experience',{'category':'employment','title':'PRIVATE_HEALTH','description':'mental health private disclosure','confirmed':True})
 off=summary.payload(u,summary.Request(expected_revision=0,request_token='fictional-source',notes='I enjoy planning before working.'))
 assert 'Scheduling project' not in json.dumps(off)
 on=summary.payload(u,summary.Request(expected_revision=0,request_token='fictional-source',include_profile=True,notes='I enjoy planning before working.'))
 text=json.dumps(on);assert 'Scheduling project' in text and 'UNREVIEWED_SECRET' not in text and 'mental health private disclosure' not in text
 assert on['profile_revision'] and any(v.get('record_id')==project['id'] and v.get('updated_at') for v in on['source_statements'])

def test_full_length_upload_and_csp(client,account,providers):
 s,q=ready(client,account)
 # More than the generic 1 MB request limit, still within the explicit audio limit.
 assert len(wav(23))>1024*1024
 r=wait(client,start(client,s,q,raw=wav(23)));assert r['status']=='completed'
 assert "media-src 'self' blob:" in client.get('/api/interview-practice/audio-options').headers['content-security-policy']

def test_narration_metadata_only_and_token_binding(client,account,monkeypatch):
 s,q=ready(client,account);calls=[]
 async def narrator(user,text,voice):calls.append((text,voice));return wav()
 monkeypatch.setattr(audio,'narrate_provider',narrator)
 b={'question_id':q['id'],'voice':'marin','request_token':'fictional-narration'}
 path='/api/interview-practice/sessions/'+s['id']+'/narration';r=client.post(path,json=b);v=wait(client,r);assert v['status']=='completed',v
 assert 'base64' not in json.dumps(v) and len(calls)==1
 assert client.post(path,json=b).json()['task_id']==r.json()['task_id']
 assert client.post(path,json={**b,'voice':'cedar'}).status_code==409
 assert client.get('/api/interview-practice/voice-playback/'+b['request_token']).json()['base64']
 audio._playback.clear();assert client.get('/api/interview-practice/voice-playback/'+b['request_token']).status_code==410

@pytest.mark.parametrize('kind',['behavioral','star','coding','case','domain','presentation','other'])
def test_material_all_modes_and_approved_summary_revocation(client,account,monkeypatch,kind):
 u=account['id'];credentials.save(u,'sk-fictional-modes')
 work_preferences.put(work_preferences.Change(expected_revision=0,summary='I like time to prepare before discussing an idea.',reviewed=True,use_for_ai=True),{'id':u})
 s=create(client,kind=kind);d=question(client,s);q=d['questions'][0];s=d['session']
 assert not any(v['kind']=='work_summary' for v in practice.context(u,s)[1])
 change=client.patch('/api/interview-practice/sessions/'+s['id']+'/context',json={'expected_updated_at':s['updated_at'],'use_work_styles':True});assert change.status_code==200
 s=change.json()['session'];sources=practice.context(u,s)[1];assert [v for v in sources if v['kind']=='work_summary'][0]['text'].startswith('I like time')
 async def model(schema,payload,*a,**k):
  assert schema==practice.PracticeMaterial
  assert not any('scores' in v for v in payload['source_catalog'])
  return {'kind':'case','title':'Illustrative case','text':'A fictional team has limited time. Explain the tradeoffs.','visuals':[],'references':[]},{'model':'fictional'}
 monkeypatch.setattr(ai,'structured',model)
 result=wait(client,client.post('/api/interview-practice/sessions/'+s['id']+'/actions',json=body(s,'material',question_id=q['id'])));assert result['status']=='completed',result
 assert len(load(client,s['id'])['materials'])==1
 current=work_preferences.read(u);work_preferences.put(work_preferences.Change(expected_revision=current['revision'],summary=current['summary'],reviewed=True,use_for_ai=False),{'id':u})
 assert not any(v['kind']=='work_summary' for v in practice.context(u,s)[1])
 exported=client.get('/api/account/export').json();r=client.post('/api/account/import',files={'file':('backup.json',json.dumps(exported).encode(),'application/json')});assert r.status_code==200,r.text
 again=client.get('/api/account/export').json();r=client.post('/api/account/import',files={'file':('again.json',json.dumps(again).encode(),'application/json')});assert r.status_code==200,r.text


def test_audio_missing_usage_is_unknown(client,account):
 event=audio.begin(account['id'],audio.DELIVERY,'interview_delivery','Fictional observation')
 audio.finish(account['id'],event,{'usage':{'prompt_tokens':20,'completion_tokens':5}},'completed',audio.DELIVERY)
 saved=db.get(account['id'],event['id'],'usage_event')['data']
 assert saved['estimated_cost_usd'] is None and saved['partial'] is True

def test_provider_wire_and_unavailable_models_do_not_retry(client,account,monkeypatch):
 import httpx
 credentials.save(account['id'],'sk-fictional-wire');original=httpx.AsyncClient;calls=[]
 async def transport(request):
  calls.append(request)
  if request.url.path.endswith('/transcriptions'):
   assert b'gpt-transcribe' in request.content and b'RIFF' in request.content
   return httpx.Response(200,json={'text':'I built a tool.','usage':{'type':'duration','seconds':1}})
  value=json.loads(request.content);assert value['model']==audio.DELIVERY and value['modalities']==['text'] and value['store'] is False
  assert value['messages'][1]['content'][0]['input_audio']['format']=='wav'
  return httpx.Response(403,json={'error':{'message':'Fictional model unavailable'}})
 monkeypatch.setattr(audio.httpx,'AsyncClient',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(transport)))
 assert asyncio.run(audio.provider(account['id'],audio.TRANSCRIBE,bytearray(wav())))['text']=='I built a tool.'
 with pytest.raises(audio.ServiceError):asyncio.run(audio.provider(account['id'],audio.DELIVERY,bytearray(wav())))
 assert len(calls)==2
 events=db.list_entities(account['id'],'usage_event');assert len(events)==2
 assert {e['data']['process'] for e in events}=={'interview_transcription','interview_delivery'}
 assert any(e['data']['estimated_cost_usd']==.000075 for e in events)
 assert any(e['data']['status']=='rejected' and e['data']['estimated_cost_usd'] is None for e in events)

def test_narration_realtime_wire_is_bounded_and_server_side(client,account,monkeypatch):
 from types import SimpleNamespace
 credentials.save(account['id'],'sk-fictional-narration-wire');sent=[]
 class Socket:
  async def __aenter__(self):return self
  async def __aexit__(self,*a):pass
  async def send_json(self,data):sent.append(data)
  def __aiter__(self):
   async def events():
    for v in [{'type':'session.updated'},{'type':'response.output_audio.delta','delta':__import__('base64').b64encode(b'\0\0'*2400).decode()},{'type':'response.done','response':{'status':'completed','usage':{'input_tokens':10,'output_tokens':100,'input_token_details':{'audio_tokens':0,'cached_tokens':0},'output_token_details':{'audio_tokens':100}}}}]:yield SimpleNamespace(type=audio.aiohttp.WSMsgType.TEXT,data=json.dumps(v))
   return events()
 class Client:
  def __init__(self,**k):pass
  async def __aenter__(self):return self
  async def __aexit__(self,*a):pass
  def ws_connect(self,url,**k):
   assert url.endswith('model='+audio.NARRATE) and k['headers']['Authorization'].startswith('Bearer ')
   return Socket()
 monkeypatch.setattr(audio.aiohttp,'ClientSession',Client)
 raw=asyncio.run(audio.narrate_provider(account['id'],'Describe a project.','marin'));assert raw.startswith(b'RIFF')
 assert len(sent)==2 and sent[0]['session']['audio']['input']['turn_detection'] is None
 assert sent[1]['response']['conversation']=='none' and sent[1]['response']['max_output_tokens']<=12000
 assert len(db.list_entities(account['id'],'usage_event'))==1

def test_api_cancel_discards_recording_and_keeps_transcript(client,account,monkeypatch):
 s,q=ready(client,account);buffers=[]
 async def provider(user,model,raw):
  buffers.append(raw)
  if model==audio.TRANSCRIBE:return {'text':'Completed transcript before cancellation.'}
  await asyncio.sleep(30)
 monkeypatch.setattr(audio,'provider',provider)
 r=start(client,s,q)
 for _ in range(100):
  rows=client.get('/api/interview-practice/sessions/'+s['id']+'/voice').json()
  if rows and rows[0]['data']['transcript']:break
  time.sleep(.01)
 assert client.delete('/api/interview-practice/sessions/'+s['id']).status_code==409
 result=client.post('/api/tasks/'+r.json()['task_id']+'/cancel');assert result.status_code==200
 for _ in range(100):
  if all(not b for b in buffers):break
  time.sleep(.01)
 assert buffers and all(not b for b in buffers)
 rows=client.get('/api/interview-practice/sessions/'+s['id']+'/voice').json();assert rows[0]['data']['transcript'].startswith('Completed')
 assert client.delete('/api/interview-practice/sessions/'+s['id']).status_code==200
