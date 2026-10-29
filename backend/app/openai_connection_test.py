"""Explicit one-request test of an account key. No Profile or credential in task payloads."""
import asyncio,json,time
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from . import auth,db,credentials,ai,ai_settings
from .models import StrictModel
from .network import ServiceError
router=APIRouter(prefix='/api/settings/openai-key/test')
def init(c):
 c.execute('CREATE TABLE IF NOT EXISTS cc_openai_tests(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,token TEXT NOT NULL,credential_revision TEXT NOT NULL,task_id TEXT NOT NULL,model TEXT NOT NULL,checked_at TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(user_id,token))')
def options(user):
 o=ai_settings.resolve(db.settings(user));efforts=ai_settings.CATALOG.get(o['model'],{}).get('efforts',ai_settings.EFFORTS);return {'model':o['model'],'reasoning_effort':efforts[0],'service_tier':'default','max_output_tokens':ai_settings.output_limit(db.settings(user),512,ceiling=512)}
def public(user):
 version=credentials.revision(user)
 if not version:return {'status':'not_configured','tested_at':None,'tested_model':None}
 with db.connect() as c:row=c.execute('SELECT x.*,t.status AS task_status FROM cc_openai_tests x JOIN tasks t ON t.id=x.task_id AND t.user_id=x.user_id WHERE x.user_id=? AND x.credential_revision=? ORDER BY x.rowid DESC LIMIT 1',(user,version)).fetchone()
 if not row:return {'status':'saved_not_tested','tested_at':None,'tested_model':None}
 result=json.loads(row['result']);status='tested_successfully' if row['task_status']=='completed' and result.get('success') else 'testing' if row['task_status'] in ('queued','running','cancelling') else 'test_cancelled' if row['task_status']=='cancelled' else 'test_failed'
 return {'status':status,'tested_at':row['checked_at'] or None,'tested_model':row['model'],'test_task_id':row['task_id'],'failure_category':result.get('failure_category'),'test_message':result.get('message','')}
@router.get('/estimate')
def estimate(user=Depends(auth.current)):
 o=options(user['id']);rate=ai_settings.rates(o['model']);usd=(96*rate['input']+512*rate['output'])/1e6 if rate else None
 return {**o,'usd':usd,'configured':bool(credentials.get(user['id'])),'input_tokens_assumed':96,'note':'One short text-generation request, lowest supported reasoning and Standard speed. No tools or Profile. This does not test voice or every feature.'}
class Test(StrictModel):
 request_token:str=Field(min_length=8,max_length=100,pattern=r'^[a-zA-Z0-9_-]+$')
 expected_model:str=Field(min_length=1,max_length=100)

def classify(message):
 if '401' in message:return 'invalid_credentials'
 if '403' in message or '404' in message or 'model is unavailable' in message:return 'model_or_permissions'
 if any(v in message for v in ('credits','spending','quota')):return 'billing_or_quota'
 if '429' in message:return 'rate_limited'
 if 'settings' in message:return 'request_settings'
 return 'temporary_or_unconfirmed'
def install(app,start_task):
 @router.post('')
 async def test(body:Test,user=Depends(auth.current)):
  u=user['id'];version=credentials.revision(u)
  if not version:raise HTTPException(422,'Save your account OpenAI key before testing it.')
  o=options(u)
  if o['model']!=body.expected_model:raise HTTPException(409,'Your selected model changed. Review the new test estimate before testing.')
  with db.connect() as c:old=c.execute('SELECT * FROM cc_openai_tests WHERE user_id=? AND token=?',(u,body.request_token)).fetchone()
  if old:
   if old['credential_revision']!=version or old['model']!=o['model']:raise HTTPException(409,'This test token belongs to an earlier key or model. Start a new test explicitly.')
   with db.connect() as c:t=c.execute('SELECT status FROM tasks WHERE id=? AND user_id=?',(old['task_id'],u)).fetchone()
   return {'task_id':old['task_id'],'status':t['status'] if t else 'interrupted'}
  async def execute():
   result={}
   try:
    if credentials.revision(u)!=version:raise ServiceError('The saved key changed. Start a new test explicitly.')
    reply=await asyncio.wait_for(ai.call_api({'model':o['model'],'input':'Reply with exactly OK.','reasoning':{'effort':o['reasoning_effort']},'service_tier':'default','max_output_tokens':o['max_output_tokens'],'store':False},retry_allowed=False),60)
    if not ai.output_text(reply).strip():raise ServiceError('The test returned no text. Access could not be fully verified; no retry was sent.')
    result={'success':True,'model':o['model'],'message':'A short text response completed successfully. Voice and other features were not tested.'}
    return result
   except asyncio.CancelledError:raise
   except Exception as error:
    message=str(error) if isinstance(error,ServiceError) else 'The test could not be confirmed. It may have incurred usage; check saved status before explicitly testing again.'
    result={'success':False,'failure_category':classify(message),'message':message};raise ServiceError(message) from None
   finally:
    if result:
     # This status is visible only if the task publishes successfully and the
     # saved credential revision still matches. No credential digest leaves DB.
     with db.connect() as c:c.execute('UPDATE cc_openai_tests SET checked_at=?,result=? WHERE user_id=? AND token=? AND credential_revision=?',(db.now(),json.dumps(result),u,body.request_token,version))
  with db.connect() as c:
   if c.execute("SELECT 1 FROM tasks WHERE user_id=? AND kind='openai_connection_test' AND status IN ('queued','running','cancelling')",(u,)).fetchone():raise HTTPException(409,'A key test is already running. Check its saved status first.')
  started=start_task(u,'openai_connection_test',execute,body.model_dump())
  with db.connect() as c:c.execute('INSERT OR IGNORE INTO cc_openai_tests VALUES(?,?,?,?,?,?,?)',(u,body.request_token,version,started['task_id'],o['model'],'','{}'))
  return started
 app.include_router(router)
