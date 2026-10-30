"""Audio estimates and transcript tokens are independent; unknown never means zero."""
import json
import pytest
from app import interview_audio as audio,db
from test_interview_practice import wait
from test_voice_and_weekly import ready,start,delivery

@pytest.mark.parametrize('text,count',[
 ('Um, UH... erm; er, hmm. Ummm! Uhhh? Ermmm; uhm.',9),
 ('Summer, human, permanent, Erin, rhythm and humming.',0),
 ('Uh-huh, yes. Uh-oh. Um—uh.',2),
 ('A clear answer without filler words.',0),
])
def test_transcript_variants_are_text_tokens_only(text,count):assert audio.transcript_fillers(text)==count

@pytest.mark.parametrize('estimate',[
 {'count':-1,'sounds':['um']},{'count':True,'sounds':['um']},
 {'count':2.5,'sounds':['uh']},{'count':'2','sounds':['uh']},
 {'count':0,'sounds':['um']},{'count':3,'sounds':[]},
 {'count':3,'sounds':['invented']},{'count':99999,'sounds':['uh']},
])
def test_bad_optional_estimate_keeps_delivery_without_claiming_zero(estimate):
 result=audio.delivery_result({**delivery(),'fillers':estimate})
 assert result['audibility']=='Clearly audible.' and result['fillers'] is None


def test_legacy_delivery_and_unknown_estimates_remain_compatible():
 assert audio.delivery_result(delivery())['fillers'] is None
 assert audio.delivery_result({**delivery(),'fillers':{'count':None,'sounds':[],'note':'Cannot reliably estimate.'}})['fillers']['count'] is None
 assert audio.delivery_result({**delivery(),'fillers':{'count':0,'sounds':[]}})['fillers']['count']==0
 with pytest.raises(ValueError):audio.delivery_result(None)


def test_cleaned_transcript_does_not_mask_audio_fillers_and_backup_preserves_estimate(client,account,monkeypatch):
 s,q=ready(client,account);calls=[];buffers=[]
 async def provider(user,model,raw):
  calls.append(model);buffers.append(raw)
  if model==audio.TRANSCRIBE:return {'text':'I automated the workflow and checked the outputs.'}
  return {'choices':[{'message':{'content':json.dumps({**delivery(),'fillers':{'count':3,'sounds':['um','uh','erm'],'note':'Includes prolonged sounds.'}})}}]}
 monkeypatch.setattr(audio,'provider',provider)
 token='fictional-fillers-'+db.uid();request=start(client,s,q,token);assert wait(client,request)['status']=='completed'
 row=client.get('/api/interview-practice/sessions/'+s['id']+'/voice').json()[0]
 assert row['data']['metrics']['audible_fillers_in_transcript']==0
 assert row['data']['delivery']['fillers']['count']==3
 assert calls==[audio.TRANSCRIBE,audio.DELIVERY] and all(not b for b in buffers)
 assert start(client,s,q,token).json()['task_id']==request.json()['task_id'] and len(calls)==2
 corrected=client.put('/api/interview-practice/voice/'+row['id']+'/transcript',json={'expected_updated_at':row['updated_at'],'transcript':'Um, I automated the workflow.','reviewed':True})
 assert corrected.status_code==200 and corrected.json()['data']['delivery']==row['data']['delivery']
 backup=client.get('/api/account/export').json()
 assert client.post('/api/account/import',files={'file':('backup.json',json.dumps(backup).encode(),'application/json')}).status_code==200
 assert db.get(account['id'],row['id'])['data']['delivery']['fillers']['count']==3


def test_delivery_estimate_survives_transcription_failure_without_extra_request(client,account,monkeypatch):
 s,q=ready(client,account);calls=[]
 async def provider(user,model,raw):
  calls.append(model)
  if model==audio.TRANSCRIBE:raise audio.ServiceError('Fictional failed transcript')
  return {'choices':[{'message':{'content':json.dumps({**delivery(),'fillers':{'count':2,'sounds':['uh'],'note':'Approximate.'}})}}]}
 monkeypatch.setattr(audio,'provider',provider)
 assert wait(client,start(client,s,q))['status']=='completed'
 row=client.get('/api/interview-practice/sessions/'+s['id']+'/voice').json()[0]
 assert row['data']['state']=='partial' and not row['data']['transcript']
 assert row['data']['delivery']['fillers']['count']==2 and calls==[audio.TRANSCRIBE,audio.DELIVERY]


def test_provider_requests_preserve_fillers_and_estimate_from_audio_without_extra_calls(client,account,monkeypatch):
 import asyncio,httpx
 from test_voice_and_weekly import wav
 ready(client,account);requests=[]
 class FakeClient:
  def __init__(self,*args,**kwargs):pass
  async def __aenter__(self):return self
  async def __aexit__(self,*args):pass
  async def post(self,url,**kwargs):
   requests.append((url,kwargs))
   return httpx.Response(200,json={'text':'Ummm, I checked it.'} if url.endswith('/transcriptions') else {'choices':[{'message':{'content':json.dumps(delivery())}}]})
 monkeypatch.setattr(audio.httpx,'AsyncClient',FakeClient)
 for model in (audio.TRANSCRIBE,audio.DELIVERY):asyncio.run(audio.provider(account['id'],model,bytearray(wav())))
 assert len(requests)==2
 assert 'Preserve audible filled pauses' in requests[0][1]['data']['prompt']
 assert 'ummm' in requests[0][1]['data']['prompt']
 instruction=requests[1][1]['json']['messages'][0]['content']
 assert all(v in instruction for v in ('directly from the AUDIO','one continuous sound counts once','never use zero to mean unavailable','Do not infer a count from the duration'))
 assert requests[1][1]['json']['store'] is False
 assert requests[1][1]['json']['messages'][1]['content'][0]['type']=='input_audio'
