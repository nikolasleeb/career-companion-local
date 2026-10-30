"""One account-owned sharing choice; legacy exclusions remain effective until saved."""
import hashlib,json
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from . import auth,db
from .models import StrictModel

router=APIRouter(prefix='/api/profile/personalization')
KIND='profile_personalization'
def identity(user):return hashlib.sha256((user+':'+KIND).encode()).hexdigest()[:32]
def read(user):
 row=db.get(user,identity(user),KIND)
 return (row or {}).get('data',{'revision':0,'enabled':True,'explicit':False})
def allowed(user,scope='profile'):
 value=read(user)
 if not value['enabled']:return False
 if value.get('explicit') or scope=='profile':return True
 kind='work_preferences' if scope=='work_styles' else 'career_goals'
 module=__import__('app.'+kind,fromlist=['identity'])
 legacy=db.get(user,module.identity(user),kind)
 return bool(legacy and legacy['data'].get('use_for_ai'))
def stamp(user):return {**read(user),'summary_shared':allowed(user,'work_styles'),'goals_shared':allowed(user,'goals')}
def request_version(user):
 """Detect edits/revocation during provider waits without writing historical snapshots."""
 rows=[(r['id'],r['data']) for kind in ('experience','profile_answer','work_preferences','career_goals',KIND) for r in db.list_entities(user,kind)]
 return hashlib.sha256(json.dumps(sorted(rows),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def check_request(user,version):
 if request_version(user)!=version:raise HTTPException(409,'Profile or personalization changed during this request. Your saved work is preserved; review the current context before starting another request.')
class Change(StrictModel):
 expected_revision:int=Field(ge=0)
 enabled:bool
@router.get('')
def get(user=Depends(auth.current)):return stamp(user['id'])
@router.put('')
def put(body:Change,user=Depends(auth.current)):
 from .resume_conversation import write
 uid=user['id']
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute('SELECT payload FROM entities WHERE user_id=? AND id=? AND kind=?',(uid,identity(uid),KIND)).fetchone()
  previous=json.loads(row[0]) if row else {'revision':0}
  if previous['revision']!=body.expected_revision:raise HTTPException(409,'Personalization changed in another window. Your choice is preserved; load the latest setting before saving.')
  write(c,uid,KIND,{'revision':previous['revision']+1,'enabled':body.enabled,'explicit':True},identity(uid))
 return stamp(uid)
