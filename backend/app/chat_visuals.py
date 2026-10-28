"""Declarative visuals and explicit, account-private image generation."""
import asyncio,base64,hashlib,io,json
from typing import Literal
import httpx
from PIL import Image
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
from pydantic import Field
from . import db,auth,onboarding,ai,credentials,storage,cost_history,task_progress
from .models import StrictModel
from .network import ServiceError
router=APIRouter(prefix='/api/chat-visuals')
IMAGE_MODEL='gpt-image-2.5-flare'
class Item(StrictModel):
 label:str=Field(max_length=160)
 text:str=Field(default='',max_length=700)
 value:float|None=None
class Visual(StrictModel):
 kind:Literal['bar','line','timeline','table','flow','sourced_image']
 title:str=Field(max_length=160)
 caption:str=Field(default='',max_length=700)
 items:list[Item]=Field(default_factory=list,max_length=30)
 source_ids:list[str]=Field(default_factory=list,max_length=8)
 illustrative:bool=False
 url:str=Field(default='',max_length=2000)
 alt:str=Field(default='',max_length=500)
VISUAL_INSTRUCTIONS=''' Optional visuals must use the supplied Visual schema: bar/line for sourced quantitative data, timeline for explicit targets, table for comparisons, flow for sequential explanatory steps, sourced_image only for a supplied verified source URL. Always include a text caption. Never invent measured values, skill scores, hiring percentages or unsupported statistics. Set illustrative=true for hypothetical examples or suggested schedules. Give source_ids from supplied evidence. Prefer a small useful visual over decoration. Never return HTML, JavaScript, executable code, SVG or remote embeds.'''
def validate(values,sources):
 from . import coach_knowledge
 ids={s.get('id',s.get('source_id',s.get('chunk_id',''))):s for s in sources}
 result=[]
 for value in values[:3]:
  v=Visual.model_validate(value).model_dump()
  if any(k not in ids for k in v['source_ids']):raise ServiceError('A visual referenced unavailable evidence. Previous results are unchanged.')
  if v['url'] and (v['kind']!='sourced_image' or not coach_knowledge.safe_url(v['url']) or not any(s.get('url')==v['url'] for s in ids.values())):raise ServiceError('An image source was not verified.')
  if v['kind'] in ('bar','line'):
   import math
   if not v['items'] or any(i['value'] is None or not math.isfinite(i['value']) for i in v['items']):raise ServiceError('A chart needs finite, supported values.')
   evidence=' '.join(str(ids[k].get('text','')) for k in v['source_ids'])
   if not v['illustrative'] and (not evidence or any(ai.numeric_facts(str(i['value']).removesuffix('.0'))-ai.numeric_facts(evidence) for i in v['items'])):raise ServiceError('Chart values were not supported by the cited evidence.')
  result.append(v)
 return result
class Generate(StrictModel):
 conversation_id:str=Field(max_length=64)
 conversation_kind:Literal['assistant_chat','coach_chat','interview_session']
 prompt:str=Field(min_length=5,max_length=4000)
 alt:str=Field(default='AI-generated career illustration',max_length=500)
 request_token:str=Field(min_length=8,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
def owner(user=Depends(auth.current)):
 onboarding.require_complete(user['id']);return user['id']
def parent(user,kind,id):
 if not db.get(user,id,kind):raise HTTPException(404,'Conversation not found.')
def active(user,kind,id):
 with db.connect() as c:
  for r in c.execute("SELECT id,result FROM tasks WHERE user_id=? AND kind='chat_image' AND status IN ('queued','running','cancelling')",(user,)):
   d=json.loads(r['result'] or '{}');inputs=d.get('_task_inputs',d.get('inputs',{}))
   if inputs.get('conversation_kind')==kind and inputs.get('conversation_id')==id:return {'id':r['id'],'inputs':inputs}
 return None
def public(r):return {**r,'data':{k:v for k,v in r['data'].items() if k!='base64'}}
@router.get('/images')
def images(conversation_id:str,conversation_kind:str,user=Depends(owner)):
 if conversation_kind not in ('assistant_chat','coach_chat','interview_session'):raise HTTPException(422,'Choose a supported conversation.')
 parent(user,conversation_kind,conversation_id)
 return [public(r) for r in db.list_entities(user,'chat_image') if r['data']['conversation_id']==conversation_id and r['data']['conversation_kind']==conversation_kind]
@router.get('/images/{id}')
def download(id:str,user=Depends(owner)):
 row=db.get(user,id,'chat_image')
 if not row:raise HTTPException(404,'Image not found.')
 parent(user,row['data']['conversation_kind'],row['data']['conversation_id'])
 return Response(base64.b64decode(row['data']['base64']),media_type='image/png',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Disposition':'inline; filename="career-illustration.png"'})
def checked_image(raw):
 if len(raw)>10*1024*1024:raise ServiceError('The generated image exceeds the 10 MB limit.')
 try:
  with Image.open(io.BytesIO(raw)) as im:
   if im.format!='PNG' or im.size!=(1024,1024):raise ValueError()
   im.verify()
 except Exception:raise ServiceError('The image response could not be validated.') from None
 return raw
async def generate(user,body):
 parent(user,body.conversation_kind,body.conversation_id)
 identity=hashlib.sha256((user+':image:'+body.request_token).encode()).hexdigest()[:32]
 old=db.get(user,identity,'chat_image')
 if old:return public(old)
 wire={'model':IMAGE_MODEL,'prompt':body.prompt,'n':1,'size':'1024x1024','quality':'medium','output_format':'png','moderation':'auto'}
 context=ai._context.get() or {};event=cost_history.begin(context,wire);result=None;status='unknown'
 try:
  task_progress.provider_wait()
  async with httpx.AsyncClient(timeout=httpx.Timeout(480,connect=15),trust_env=False) as client:
   response=await client.post('https://api.openai.com/v1/images/generations',headers={'Authorization':'Bearer '+credentials.get(user)},json=wire)
  result=response.json()
  if response.status_code>=400:
   status='rejected' if response.status_code<500 else 'failed'
   raise ServiceError('Image generation is unavailable for this account or model. Check your API access and allowance. No substitute model or automatic retry was used.')
  raw=checked_image(base64.b64decode(result['data'][0]['b64_json'],validate=True));status='completed'
 except (httpx.HTTPError,KeyError,ValueError):raise ServiceError('Image generation did not return a confirmed image. It may have incurred usage; check status before explicitly trying again.') from None
 finally:
  if event:
   usage=(result or {}).get('usage') or {};details=usage.get('input_tokens_details') or {};text=details.get('text_tokens');image=details.get('image_tokens');out=usage.get('output_tokens')
   known=all(type(v) is int and v>=0 for v in (text,image,out));cost=(text*5+image*8+out*30)/1000000 if known else None
   cost_history.write(user,{**event['data'],'status':status,'usage_reported':bool(usage),**cost_history.token_flags(usage),**cost_history.normalized(usage),'input_tokens':usage.get('input_tokens',0) if type(usage.get('input_tokens')) is int else 0,'output_tokens':out if type(out) is int else 0,'token_cost_usd':cost,'tool_cost_usd':0 if known else None,'estimated_cost_usd':cost,'partial':not known,'rates':{},'notes':['Image API · 1 image · 1024×1024 · medium. Text input $5/M, image input $8/M, image output $30/M; checked 2026-10-25.', 'Actual provider bill may differ; unreported usage is unknown.']},event['id'])
  task_progress.provider_done()
 storage.ensure_capacity(len(raw)*2+65536)
 row=db.save(user,'chat_image',{'conversation_id':body.conversation_id,'conversation_kind':body.conversation_kind,'base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest(),'alt':body.alt,'model':IMAGE_MODEL,'quality':'medium','size':'1024x1024','request_token':body.request_token,'generated_at':db.now()},identity)
 return public(row)
def install(app,start_task,require_ai):
 @router.post('/generate')
 async def start(body:Generate,user=Depends(owner)):
  parent(user,body.conversation_kind,body.conversation_id);require_ai(user)
  previous=active(user,body.conversation_kind,body.conversation_id)
  if previous and previous['inputs'].get('request_token')!=body.request_token:raise HTTPException(409,'An illustration is already running for this conversation. Check its saved status first.')
  if not credentials.get(user):raise ServiceError('Add your own OpenAI key before generating an illustration.')
  return start_task(user,'chat_image',lambda:generate(user,body),body.model_dump())
 app.include_router(router)
def validate_backup(record,kinds):
 if record['kind']!='chat_image':return
 d=record['data']
 if d.get('conversation_kind') not in ('assistant_chat','coach_chat','interview_session') or kinds.get(d.get('conversation_id'))!=d['conversation_kind']:raise ValueError()
 raw=checked_image(base64.b64decode(d['base64'],validate=True))
 if hashlib.sha256(raw).hexdigest()!=d['sha256'] or len(d.get('alt',''))>500:raise ValueError()
