"""Career Coach access registry: explicit projections, never arbitrary entity dumps.

New saved features must register an eligibility/projection rule here. Private
vaults, settings/secrets, raw assessment answers, drafts and conversation-only
offers have no automatic adapter. Read permissions are rechecked every request.
"""
import json,re
from . import db,profile_answers,work_preferences,career_goals
REGISTRY={
 'resume':'Finalized generated resume','resume_revision':'Finalized resume revision',
 'cover_letter':'Finalized generated cover letter','application':'Application tracking',
 'job':'Employer posting','analysis':'Completed generated posting analysis',
 'prep':'Saved generated skills plan','coach_plan':'Reviewed generated career plan',
 'saved_career':'Saved career interest','career_explorer_search':'Saved career search',
 'project_analysis':'Completed generated project analysis','career_explorer_review':'Saved generated Profile connections review',
 'interview_attempt':'Completed generated interview feedback','project_snapshot':'Prepared professional project source','document':'Reviewed professional source document',
}
DENIED_STATUS={'draft','pending','proposed','pending_review','incomplete','queued','running','failed','cancelled','interrupted','unreviewed'}
PROVENANCE=('source_snapshot','profile_snapshot','goal_snapshot','planning_inputs_snapshot','work_style_summary','work_style_considerations','suggestions','connections','feedback','actions','explicit_context_snapshot','sources','career_goal_selection','approved_context','evidence','resume_snapshot')
def text(value):return json.dumps(value,ensure_ascii=False,indent=2) if isinstance(value,(dict,list)) else str(value or '')
def pick(d,keys):return {k:d[k] for k in keys if k in d}
def consent(user):return bool(work_preferences.context(user)['preferences']),bool(work_preferences.coach_context(user)),bool(career_goals.context(user)['text'])
def source_allowed(user,value,permissions=None,excluded=()):
 """Reject gated inputs even when copied into a completed generated artifact."""
 style,report,goals=permissions or consent(user)
 visited=set()
 def check(v):
  if isinstance(v,list):return all(check(x) for x in v)
  if not isinstance(v,dict):return True
  kind=str(v.get('kind',''))
  if v.get('record_id') in excluded:return False
  if kind in ('private','private_profile','private_answer','eligibility','explicit_offer'):return False
  if kind in ('work_style_report','work_style') and not report:return False
  if kind in ('preference','work_summary','work_preferences') and not style:return False
  if kind in ('aspiration','career_goals') and not goals:return False
  for k,child in v.items():
   if k in ('private_answers','private_profile','raw_answers','assessment_answers','offer_details') and child:return False
   if k in ('work_style_summary','reviewed_work_style_summary','work_style_considerations','work_style_guidance') and child and not style:return False
   if k in ('work_style_report','assessment_report','scores') and child and not report:return False
   if k in ('profile_goals_snapshot','profile_career_goals','career_goal_selection','selected_goals_as_aspirations') and child and not goals and (not isinstance(child,dict) or any(child.get(f) for f in ('text','note','items','goal_ids'))):return False
   if k=='record_id' and isinstance(child,str) and re.fullmatch(r'[a-f0-9]{32}',child):
    row=db.get(user,child)
    if not row:return False
    rk=row['kind'];data=row['data']
    if rk=='experience' and not data.get('confirmed'):return False
    if rk=='profile_answer' and (data.get('status')!='confirmed' or data.get('answer_kind')!='experience'):return False
    if rk=='work_preferences' and not style:return False
    if rk=='career_goals' and not goals:return False
    if rk=='work_style' and (not report or kind!='work_style_report'):return False
    allowed=set(REGISTRY)|{'experience','profile_answer','work_preferences','career_goals','work_style','interview_session','interview_document','interview_research','coach_research'}
    if rk not in allowed:return False
    if rk in REGISTRY and (data.get('status') in DENIED_STATUS or data.get('state') in DENIED_STATUS or any(data.get(k) is False for k in ('reviewed','source_reviewed','confirmed'))):return False
    if rk=='resume_revision' and not data.get('finalized_resume_id'):return False
    if child not in visited:
     visited.add(child)
     if not check(pick(data,PROVENANCE)):return False
   if not check(child):return False
  return True
 return check(value)
def resume(d):
 d=d.get('snapshot',d);d=d.get('resume',d)
 return '\n'.join([str(d.get('source_text','')),str(d.get('headline','')),*[str(e.get('title',''))+'\n'+'\n'.join(str(v) for v in e.get('bullets',[])) for section in d.get('sections',[]) for e in section.get('entries',[])]])
def project(user,r,permissions=None):
 d=r['data'];kind=r['kind']
 if d.get('reviewed') is False or d.get('source_reviewed') is False:return None
 if d.get('status') in DENIED_STATUS or d.get('state') in DENIED_STATUS or d.get('confirmed') is False:return None
 if not source_allowed(user,pick(d,PROVENANCE),permissions):return None
 if kind=='resume_revision' and not d.get('finalized_resume_id'):return None
 if kind in ('resume','resume_revision'):return resume(d)
 if kind=='cover_letter':return text(pick(d.get('content',{}),('paragraphs','greeting','closing')))
 if kind=='application':
  value=pick(d,('title','company','status','applied_date','next_action','next_action_date','archived'))
  value['history']=[pick(e,('status','date')) for e in d.get('history',[])]
  value['interviews']=[pick(e,('date','type')) for e in d.get('interviews',[])]
  # Freeform tracker notes/outcomes can contain conversation-only offer details.
  return ('Historical record. Not a current application.\n' if d.get('archived') else '')+text(value)
 if kind=='job':return None if d.get('cache_tombstone') else text(pick(d,('title','company','location','description')))
 if kind=='analysis':return text(pick(d,('summary','suggestions')))
 if kind=='prep':return text(pick(d,('priorities','steps','title','resources','summary')))
 if kind=='coach_plan':
  from . import plan_progress
  return text({**pick(d,('direction','actions')),'checklist':plan_progress.source_snapshot(user,r)})
 if kind=='saved_career':return text(pick(d,('code','title')))
 if kind=='career_explorer_search':return text(pick(d,('name','query','course_refs')))
 if kind=='project_analysis':
  if not d.get('summary') or 'findings' not in d:return None
  return text({'summary':d['summary'],'findings':[pick(f,('file_path','quote','observation')) for f in d['findings']]})
 if kind=='career_explorer_review':
  from . import career_reviews
  value=pick(d,('code','connections','limitations'));value['outdated']=career_reviews.public(user,r)['outdated']
  # The workplace interpretation is available only through current summary consent.
  if work_preferences.context(user)['preferences']:value['work_style_considerations']=d.get('work_style_considerations',[])
  return text(value)
 if kind in ('project_snapshot','document'):
  linked=[e for e in db.list_entities(user,'experience') if e['data'].get('confirmed')]
  if kind=='project_snapshot':
   if not any(e['id']==d.get('experience_id') for e in linked) or not any(a['data'].get('snapshot_id')==r['id'] and project(user,a,permissions) for a in db.list_entities(user,'project_analysis')):return None
   return '\n'.join(str(f.get('file_path',''))+'\n'+str(f.get('text','')) for f in d.get('files',[]))
  references=[ref.get('document_id') for e in linked for ref in e['data'].get('source_references',[])]+[c.get('document_id') for e in linked for c in e['data'].get('certification_items',[])]
  return d.get('text','') if r['id'] in references else None
 if kind=='interview_attempt':
  if not isinstance(d.get('feedback'),dict):return None
  session=db.get(user,d.get('session_id',''),'interview_session')
  if session and session['data'].get('use_work_styles') and not work_preferences.context(user)['preferences']:return None
  return text(pick(d['feedback'],('summary','strengths','improvements','claims_to_clarify','follow_up','correctness','complexity','edge_cases')))
 return None

def records(user,excluded=()):
 permissions=consent(user)
 for r in db.list_entities(user,'experience'):
  d=r['data']
  if not d.get('confirmed'):continue
  value=pick(d,('category','title','organization','location','description','contribution','tools','accomplishments','dates','start_date','end_date','expected_graduation','degree','major','minor','majors','minors','concentration','gpa','gpa_scale','honors','relevant_courses','work_arrangement','skill_items','individual_project'))
  if d.get('certification_items'):value['certifications']=[pick(c,('name','issuer','earned_date','expiration_date','does_not_expire')) for c in d['certification_items']]
  yield {'record_id':r['id'],'kind':'reviewed_profile','label':'Reviewed Profile · '+str(d.get('title') or d.get('organization') or d.get('category','record')),'revision':r['updated_at'],'status':'confirmed','text':text(value)}
 for r in profile_answers.confirmed(user):
  if r['data'].get('answer_kind')=='experience':yield {'record_id':r['id'],'kind':'reviewed_profile','label':'Reviewed Supporting Details · '+r['data'].get('title','Professional experience'),'revision':r['updated_at'],'status':'confirmed','text':r['data'].get('text') or r['data'].get('answer','')}
 with db.connect() as c:rows=[db.decode(r) for r in c.execute('SELECT * FROM entities WHERE user_id=? AND kind IN ('+','.join('?' for _ in REGISTRY)+') ORDER BY updated_at DESC',(user,*REGISTRY))]
 for r in rows:
  provenance=pick(r['data'],PROVENANCE)
  if r['id'] in excluded or not source_allowed(user,provenance,permissions,excluded):continue
  value=project(user,r,permissions)
  if value and value not in ('{}','[]'):
   label=('Archived application · historical record' if r['data'].get('archived') else 'Application') if r['kind']=='application' else REGISTRY[r['kind']]
   status='saved_record' if r['kind'] in ('application','job','document','project_snapshot','saved_career','career_explorer_search') else 'saved_output'
   yield {'record_id':r['id'],'kind':r['kind'],'label':label+' · '+str(r['data'].get('title') or r['data'].get('name') or r['data'].get('company') or r['data'].get('code') or ''),'revision':r['updated_at']+(':progress:'+str((__import__('app.plan_progress',fromlist=['source_snapshot']).source_snapshot(user,r) or {}).get('revision',0)) if r['kind']=='coach_plan' else ''),'status':status,'text':value}
