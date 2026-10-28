"""Account-owned deterministic multi-document proposals; approval is one transaction."""
import hashlib,json,difflib
from collections import defaultdict
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from . import auth,db,profile_import,resume_parser,onboarding,certifications,account_cleanup,storage
from .models import StrictModel,ExperienceItem,SettingsUpdate,ResumeImportEntry,ResumeImportUpdate
router=APIRouter(prefix='/api/profile-import')
META={'confirmed','source_document_id','source_entry_id','source_references','unavailable_source_ids'}
PERSONAL={'name','email','phone','city','state','country','county','website','github','linkedin'}
def init(c):c.execute('CREATE TABLE IF NOT EXISTS cc_profile_imports(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,snapshot TEXT NOT NULL,receipt TEXT NOT NULL DEFAULT \'\')')
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def text_hash(text):return hashlib.sha256(text.encode()).hexdigest()
def present(v):return v not in ('',None,[],{},False)
def same(a,b):return ' '.join(a.split()).casefold()==' '.join(b.split()).casefold() if isinstance(a,str) and isinstance(b,str) else a==b
class Prepare(StrictModel):
 document_ids:list[str]=Field(min_length=1,max_length=2)
 separate_groups:list[str]=Field(default_factory=list,max_length=200)
class Approval(StrictModel):
 reviewed:bool
 entries:list[ResumeImportEntry]=Field(default_factory=list,max_length=200)
 updates:list[ResumeImportUpdate]=Field(default_factory=list,max_length=200)
 profile_updates:SettingsUpdate=Field(default_factory=SettingsUpdate)
 choices:dict[str,dict[str,str]]=Field(default_factory=dict)
 profile_choices:dict[str,str]=Field(default_factory=dict)
 confirmed_merges:list[str]=Field(default_factory=list,max_length=200)
def source_ref(document,entry,field):return {'document_id':document['id'],'filename':document['data']['filename'],'entry_id':entry,'text_hash':text_hash(document['data']['text']),'field':field}
def compatible(a,b):
 x,y=a['data'],b['data']
 if x['category']!=y['category']:return False
 org=profile_import.normal(x.get('organization',''))
 if org!=profile_import.normal(y.get('organization','')):return False
 tx=profile_import.normal(x.get('degree') or x.get('title'));ty=profile_import.normal(y.get('degree') or y.get('title'))
 return bool(tx and ty and (tx==ty or org and x['category']=='education' and profile_import.degree(tx)==profile_import.degree(ty) or org and difflib.SequenceMatcher(None,tx,ty).ratio()>=.75))
def combine(documents,separate):
 groups=[];profiles=defaultdict(list);sources={};warnings=[];unmapped=[]
 for d in documents:
  parsed=profile_import.parse(d['data']['text'],d['data'].get('import_source_kind','resume'));sources[d['id']]={**d,'parsed':parsed}
  for k,v in parsed['profile'].items():
   if k in PERSONAL and present(v):profiles[k].append({'value':v,'source':source_ref(d,'personal',k)})
  for e in parsed['entries']:
   candidate={**e,'document_id':d['id']};found=next((g for g in groups if all(v['document_id']!=d['id'] for v in g) and compatible(g[0],candidate)),None)
   if found:found.append(candidate)
   else:groups.append([candidate])
  warnings.extend(parsed.get('warnings',[]));unmapped.extend({**r,'filename':d['data']['filename']} for r in parsed.get('unmapped',[]))
 entries=[]
 for group in groups:
  key=digest([(e['document_id'],e['id']) for e in group])[:32]
  parts=[[e] for e in group] if key in separate else [group]
  for part in parts:
   identity=digest([(e['document_id'],e['id']) for e in part])[:32];fields=defaultdict(list)
   for e in part:
    for k,v in e['data'].items():
     if k not in META and present(v):fields[k].append({'value':v,'source':source_ref(sources[e['document_id']],e['id'],k)})
   conflicts={k:v for k,v in fields.items() if any(not same(v[0]['value'],x['value']) for x in v[1:])}
   data={k:v[0]['value'] for k,v in fields.items() if k not in conflicts};data=ExperienceItem.model_validate({**data,'title':data.get('title') or 'Review title','confirmed':False}).model_dump()
   entries.append({'id':identity,'data':data,'label':part[0]['data']['title'],'source_text':'\n\n'.join(sources[e['document_id']]['data']['filename']+'\n'+e['source_text'] for e in part),'sources':[{'document_id':e['document_id'],'filename':sources[e['document_id']]['data']['filename'],'entry_id':e['id']} for e in part],'field_sources':dict(fields),'conflicts':conflicts,'requires_merge_confirmation':len(part)>1 and bool(conflicts),'warnings':list(dict.fromkeys(w for e in part for w in e.get('warnings',[])))})
 profile_conflicts={k:v for k,v in profiles.items() if any(not same(v[0]['value'],x['value']) for x in v[1:])}
 return {'entries':entries,'profile':{k:('' if k in profile_conflicts else v[0]['value']) for k,v in profiles.items()},'profile_sources':dict(profiles),'profile_conflicts':profile_conflicts,'profile_evidence':{k:'\n'.join(x['source']['filename']+': '+str(x['value']) for x in v) for k,v in profiles.items()},'warnings':list(dict.fromkeys(warnings)),'unmapped':unmapped}
def read_documents(c,user,ids):
 if len(set(ids))!=len(ids):raise HTTPException(422,'Choose each source once.')
 result=[];kinds=[]
 for id in ids:
  row=c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='document'",(id,user)).fetchone()
  if not row:raise HTTPException(404,'Source document is unavailable.')
  d=db.decode(row)
  if d['data'].get('purpose')!='resume':raise HTTPException(422,'Choose only Profile resume or LinkedIn documents.')
  kind=d['data'].get('import_source_kind','resume')
  if kind not in ('resume','linkedin_pdf') or kind in kinds:raise HTTPException(422,'Choose at most one resume and one LinkedIn PDF.')
  if not d['data'].get('text'):raise HTTPException(422,'Correct the source text before preparing review.')
  kinds.append(kind);result.append(d)
 return result
@router.post('/preview')
def prepare(body:Prepare,user=Depends(auth.current)):
 with db.connect() as c:
  documents=read_documents(c,user['id'],body.document_ids);parsed=combine(documents,body.separate_groups);profile=json.loads(c.execute('SELECT settings FROM users WHERE id=?',(user['id'],)).fetchone()[0]);rows=[db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='experience'",(user['id'],))];identity=db.uid()
  snapshot={'documents':[{'id':d['id'],'filename':d['data']['filename'],'hash':text_hash(d['data']['text']),'updated_at':d['updated_at'],'text':d['data']['text']} for d in documents],'parsed':parsed,'profile_base':{k:profile.get(k,'') for k in parsed['profile']},'comparison':profile_import.preview(parsed,rows),'cleanup_revision':account_cleanup.revision(user['id'],c),'separate_groups':body.separate_groups}
  storage.ensure_capacity(len(json.dumps(snapshot).encode())+65536)
  c.execute('INSERT INTO cc_profile_imports VALUES(?,?,?,?)',(identity,user['id'],json.dumps(snapshot),''))
  c.execute("DELETE FROM cc_profile_imports WHERE user_id=? AND receipt='' AND rowid NOT IN (SELECT rowid FROM cc_profile_imports WHERE user_id=? AND receipt='' ORDER BY rowid DESC LIMIT 10)",(user['id'],user['id']))
 return {'id':identity,'kind':'combined_import','data':{'filename':' + '.join(d['data']['filename'] for d in documents),'resume_parse':{**parsed,'text_hash':digest(snapshot)},'combined':snapshot,'text':''}}
def public_snapshot(user,id):
 with db.connect() as c:
  r=c.execute('SELECT snapshot FROM cc_profile_imports WHERE id=? AND user_id=?',(id,user)).fetchone()
  if not r:raise HTTPException(404,'This combined review is unavailable. Prepare it again.')
  return json.loads(r['snapshot'])
@router.get('/{id}/preview')
def comparison(id:str,user=Depends(auth.current)):return public_snapshot(user['id'],id)['comparison']
def resolve_fields(proposal,values,choices,fields):
 for k in fields:
  options=proposal.get('conflicts',{}).get(k)
  if not options:continue
  choice=choices.get(k)
  if choice=='omit':
   if present(values.get(k)) and values.get(k) not in ('Review title',):raise HTTPException(422,'Omitted fields must stay empty.')
  elif choice=='edited':pass
  elif choice is not None and choice.isdigit() and int(choice)<len(options):
   if values.get(k)!=options[int(choice)]['value']:raise HTTPException(422,'The chosen source and reviewed value differ.')
  else:raise HTTPException(422,'Resolve each selected conflicting field before importing.')
def provenance(proposal,data,fields,choices):
 grouped={}
 for k in fields:
  for option in proposal.get('field_sources',{}).get(k,[]):
   ref=option['source'];key=(ref['document_id'],ref['entry_id']);row=grouped.setdefault(key,{'document_id':ref['document_id'],'entry_id':ref['entry_id'],'text_hash':ref['text_hash'],'fields':[],'edited_fields':[]})
   if same(data.get(k),option['value']):row['fields'].append(k)
   elif choices.get(k)=='edited' or k not in proposal.get('conflicts',{}) and present(data.get(k)):row['edited_fields'].append(k)
 return list(grouped.values())
@router.post('/{id}/approve')
def approve(id:str,body:Approval,user=Depends(auth.current)):
 if body.reviewed is not True:raise HTTPException(422,'Review the selected changes before importing.')
 u=user['id'];updates=body.profile_updates.model_dump(exclude_none=True)
 storage.ensure_capacity(len(body.model_dump_json().encode())*3+65536)
 if set(updates)-PERSONAL:raise HTTPException(422,'Only proposed personal details may be imported.')
 if not body.entries and not body.updates and not updates:raise HTTPException(422,'Select information to import.')
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');op=c.execute('SELECT * FROM cc_profile_imports WHERE id=? AND user_id=?',(id,u)).fetchone()
  if not op:raise HTTPException(404,'Combined review is unavailable. Prepare it again.')
  approval_hash=digest(body.model_dump())
  if op['receipt']:
   receipt=json.loads(op['receipt'])
   if receipt['approval_hash']!=approval_hash:raise HTTPException(409,'This review was already imported. Prepare a new review for more changes.')
   return receipt['result']
  snap=json.loads(op['snapshot'])
  if account_cleanup.revision(u,c)!=snap['cleanup_revision']:raise HTTPException(409,'Account information changed. Prepare a new review.')
  documents=read_documents(c,u,[d['id'] for d in snap['documents']])
  for a,b in zip(snap['documents'],documents):
   if a['hash']!=text_hash(b['data']['text']) or a['updated_at']!=b['updated_at']:raise HTTPException(409,'A source changed. Prepare a new combined review; nothing was imported.')
  allowed={e['id']:e for e in snap['parsed']['entries']};selected=[*body.entries,*body.updates]
  if len({e.id for e in selected})!=len(selected) or len({e.record_id for e in body.updates})!=len(body.updates):raise HTTPException(422,'Choose each proposal and target record once.')
  profile=json.loads(c.execute('SELECT settings FROM users WHERE id=?',(u,)).fetchone()[0]);created=[];changed=[];skipped=[];stamp=db.now()
  for k,v in updates.items():
   if k not in snap['parsed']['profile'] or not present(v):raise HTTPException(422,'Choose nonempty proposed personal details.')
   if profile.get(k,'')!=snap['profile_base'].get(k,''):raise HTTPException(409,'Personal details changed. Prepare a fresh review.')
   resolve_fields({'conflicts':snap['parsed']['profile_conflicts']},{k:v},body.profile_choices,[k])
  existing=[db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='experience'",(u,))];fingerprints={resume_parser.fingerprint(r['data']):r['id'] for r in existing}
  for item in selected:
   proposal=allowed.get(item.id)
   if not proposal:raise HTTPException(422,'The proposal does not belong to this review.')
   data=item.data.model_dump();choice=body.choices.get(item.id,{})
   if data['title']=='Review title':raise HTTPException(422,'Choose or enter the actual record title.')
   if data['category']!=proposal['data']['category']:raise HTTPException(422,'Keep the proposed Profile section.')
   fields=item.fields if isinstance(item,ResumeImportUpdate) else [k for k in ExperienceItem.model_fields if k not in META and k!='category']
   if set(fields)-set(ExperienceItem.model_fields) or set(fields)&META:raise HTTPException(422,'Choose editable Profile fields.')
   if proposal['requires_merge_confirmation'] and item.id not in body.confirmed_merges:raise HTTPException(422,'Confirm these sources describe the same record, or keep them separate.')
   resolve_fields(proposal,data,choice,fields);refs=provenance(proposal,data,fields,choice);certifications.validate_documents(u,data)
   if isinstance(item,ResumeImportUpdate):
    oldrow=c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='experience'",(item.record_id,u)).fetchone()
    if not oldrow:raise HTTPException(404,'The target Profile record is unavailable.')
    if oldrow['updated_at']!=item.expected_updated_at or snap['comparison']['_versions'].get(item.record_id)!=item.expected_updated_at:raise HTTPException(409,'A Profile record changed. Prepare a fresh review.')
    old=db.decode(oldrow)['data'];patch={k:data[k] for k in fields}
    if old.get('category')!=data['category'] or any(not present(v) for v in patch.values()):raise HTTPException(422,'Updates cannot erase information or change its section.')
    merged=ExperienceItem.model_validate({**old,**patch,'source_references':edited_references(old,{**old,**patch})+refs}).model_dump();identity=item.record_id
    changed.append({'record_id':identity,'fields':fields,'before':{k:old.get(k) for k in fields},'after':patch})
    c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(merged),stamp,identity,u));c.execute('DELETE FROM evidence_fts WHERE id=? AND user_id=?',(identity,u))
    if merged.get('confirmed'):c.execute('INSERT INTO evidence_fts VALUES(?,?,?,?)',(identity,u,'experience',json.dumps(merged)))
   else:
    fingerprint=resume_parser.fingerprint(data)
    if fingerprint in fingerprints:skipped.append({'entry_id':item.id,'record_id':fingerprints[fingerprint]});continue
    identity=db.uid();merged={**data,'confirmed':True,'source_document_id':proposal['sources'][0]['document_id'],'source_entry_id':item.id,'source_references':refs,'unavailable_source_ids':[]};raw=json.dumps(merged)
    c.execute('INSERT INTO entities VALUES(?,?,?,?,?,?)',(identity,u,'experience',raw,stamp,stamp));c.execute('INSERT INTO evidence_fts VALUES(?,?,?,?)',(identity,u,'experience',raw));onboarding.profile_added(c,u,'experience',merged);created.append({'entry_id':item.id,'record_id':identity});fingerprints[fingerprint]=identity
  profile.update(updates);c.execute('UPDATE users SET settings=? WHERE id=?',(json.dumps(profile),u))
  receipt={'batch_id':id,'source_ids':[d['id'] for d in documents],'created':created,'updated':changed,'skipped':skipped,'profile_fields':list(updates),'profile_choices':body.profile_choices,'profile_values':updates,'profile_provenance':{k:snap['parsed']['profile_sources'][k] for k in updates},'imported_at':stamp}
  for document in documents:
   data=document['data'];data.update(reviewed=True,last_resume_import=receipt,import_history=[*data.get('import_history',[]),receipt]);c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(data),stamp,document['id'],u))
  result={'created':len(created),'updated':len(changed),'skipped':len(skipped),'message':f'Import complete: added {len(created)} records, updated {len(changed)}, skipped {len(skipped)} duplicates. Original documents and saved versions are kept.'}
  c.execute('UPDATE cc_profile_imports SET receipt=? WHERE id=? AND user_id=?',(json.dumps({'approval_hash':approval_hash,'result':result}),id,u))
  return result


def edited_references(old,new):
    refs=json.loads(json.dumps(old.get('source_references',[])))
    for ref in refs:
        changed=[k for k in ref['fields'] if new.get(k)!=old.get(k)]
        ref['fields']=[k for k in ref['fields'] if k not in changed]
        ref['edited_fields']=sorted(set(ref.get('edited_fields',[])+changed))
    return refs

def removed_source(user,identity):
    with db.connect() as c:
        for row in c.execute('SELECT id,snapshot FROM cc_profile_imports WHERE user_id=?',(user,)).fetchall():
            if identity in [d['id'] for d in json.loads(row['snapshot'])['documents']]:c.execute('DELETE FROM cc_profile_imports WHERE id=? AND user_id=?',(row['id'],user))
        for row in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='experience'",(user,)).fetchall():
            data=json.loads(row['payload'])
            if any(r['document_id']==identity for r in data.get('source_references',[])):
                data['unavailable_source_ids']=sorted(set(data.get('unavailable_source_ids',[])+[identity]));c.execute('UPDATE entities SET payload=?,updated_at=? WHERE id=? AND user_id=?',(json.dumps(data),db.now(),row['id'],user))
