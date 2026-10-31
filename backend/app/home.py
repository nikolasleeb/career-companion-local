"""Bounded, read-only return-to-work summaries. No providers or migrations on reads."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,Query
from . import auth,db,applications,application_preparation,daily_usage,plan_progress,job_cache,project_relations
router=APIRouter(prefix='/api/home')

def application_summary(user,visited=''):
    rows=application_preparation.decorate(user,[r for r in db.list_entities(user,'application') if r['data'].get('status')=='preparing' and not r['data'].get('archived')])
    rows.sort(key=lambda r:(r['id']==visited,r['updated_at']),reverse=True)
    return [{'id':r['id'],'job_id':r['data'].get('job_id',''),'title':r['data'].get('title','Opportunity')[:240],'company':r['data'].get('company','')[:240],'updated_at':r['updated_at'],'resume_id':r['data'].get('workflow',{}).get('resume_id',''),'preparation':r.get('preparation',{})} for r in rows[:4]]

def plans(user):
    chats={r['id']:r for r in db.list_entities(user,'coach_chat')};result=[]
    for row in db.list_entities(user,'coach_plan'):
        d=row['data'];chat=chats.get(d.get('chat_id'))
        if not chat or chat['data'].get('plan_id')!=row['id']:continue
        state=plan_progress.snapshot(user,row);next_step=None
        for action in d.get('actions',[]):
            for sid,text in zip(state['step_ids'][action['id']],action['steps']):
                if not state['steps'].get(sid,{}).get('completed'):
                    next_step={'id':sid,'milestone_id':action['id'],'text':text[:1200],'milestone':action['title'][:240]};break
            if next_step:break
        result.append({'id':row['id'],'chat_id':chat['id'],'title':(d.get('title') or chat['data'].get('title','Action plan'))[:240],'version':d.get('version',1),'updated_at':row['updated_at'],'completed':state['completed'],'total':state['total'],'percent':state['percent'],'next_step':next_step})
    return sorted(result,key=lambda r:(r['completed']<r['total'],r['updated_at']),reverse=True)[:30]

def reminders(user):
    records=db.list_entities(user,'experience');result=[]
    education=[r['data'] for r in records if r['data'].get('confirmed') and r['data'].get('category')=='education']
    if not any(d.get('organization','').strip() and (d.get('degree','').strip() or d.get('title','').strip().casefold() not in ('','education',d.get('organization','').strip().casefold())) for d in education):
        result.append({'text':'Review an education entry with a school and degree or program to unlock application tools.','tab':'resume'})
    imports=sum(r['data'].get('purpose')=='resume' and not r['data'].get('reviewed') for r in db.list_entities(user,'document'))
    if imports:result.append({'text':f'Review {imports} pending Profile import(s).','tab':'upload'})
    pending=sum(not r['data'].get('confirmed') for r in records)
    details=sum(r['data'].get('status')=='draft' or r['data'].get('needs_related_experience') for r in db.list_entities(user,'profile_answer'))
    if pending or details:result.append({'text':f'Review {pending} unconfirmed record(s) and {details} Supporting Detail(s).','tab':'resume'})
    with db.connect() as c:
        unresolved=[r for r in records if project_relations.unresolved(c,user,r['data'])]
    if unresolved:result.append({'text':f'Resolve links for {len(unresolved)} Profile record(s).','tab':'resume'})
    for r in records:
        d=r['data']
        if d.get('category') in ('employment','project') and not any(str(d.get(k,'')).strip() for k in ('description','contribution','accomplishments')):
            result.append({'text':'Add a description or contribution for '+d.get('title','this experience')[:180]+'.','tab':'resume','item':r['id']})
    return result[:3]

def suggestions(user):
    searches=db.list_entities(user,'personalized_search');latest=max(searches,key=lambda r:r['updated_at'],default=None)
    if not latest:return {'checked_at':None,'search_id':None,'jobs':[]}
    data=latest['data'];used={r['data'].get('job_id') for r in db.list_entities(user,'application')};urls={r['data'].get('url') for r in db.list_entities(user,'application') if r['data'].get('url')}
    jobs={r['id']:r for r in job_cache.decorate_records(user,db.list_entities(user,'job'))};result=[]
    for match in data.get('matches',[]):
        rid=match.get('job_id');row=jobs.get(rid)
        if not row or rid in used:continue
        d=row['data'];deadline=job_cache.deadline(d)
        if d.get('url') in urls or d.get('lifecycle_status') in ('closed','expired') or d.get('cache_tombstone') or d.get('cache_payload_purged') or d.get('source_closed_at') or deadline is not None and deadline<=datetime.now(timezone.utc).timestamp():continue
        result.append({'id':rid,'title':d.get('title','Opportunity')[:240],'company':d.get('company','')[:240],'location':d.get('location','')[:240],'url':d.get('url','')[:2000]})
    return {'checked_at':data.get('checked_at',latest['updated_at']),'search_id':data.get('search_id'),'jobs':result[:5]}

def summary(user,tz='UTC',visited=''):
    result={'errors':{},'read_only':True}
    def part(name,fn):
        try:result[name]=fn()
        except Exception:
            # A damaged legacy record must not make all return-to-work cards inaccessible.
            import logging
            logging.getLogger(__name__).exception('Home section unavailable: %s',name)
            result[name]=None;result['errors'][name]='This section could not load. Open its tool or refresh Home.'
    part('applications',lambda:application_summary(user,visited))
    part('plans',lambda:plans(user))
    part('usage',lambda:daily_usage.summary(user,tz))
    def chart():
        zone=ZoneInfo(db.settings(user).get('usage_timezone') or tz);end=datetime.now(timezone.utc).astimezone(zone).date();start=end.replace(year=end.year-1,day=min(end.day,28) if end.month==2 and end.day==29 else end.day)+timedelta(days=1)
        value=applications.dashboard(db.list_entities(user,'application'),start.isoformat(),end.isoformat(),'month',str(zone))
        return {**{k:value[k] for k in ('counts','cohort_count','nodes','links','submissions')},'start':start.isoformat(),'end':end.isoformat()}
    part('chart',chart);part('profile',lambda:reminders(user));part('suggestions',lambda:suggestions(user))
    return result

@router.get('')
def read(tz:str=Query(default='UTC',max_length=100),visited:str=Query(default='',max_length=100),user=Depends(auth.current)):
    return summary(user['id'],tz,visited)
