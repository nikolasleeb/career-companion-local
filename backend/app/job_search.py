"""Public source search and account-owned decisions. No provider keys enter records."""
import asyncio,hashlib,json,re
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse
from . import config,db,integrations as x,task_progress,ai,job_locations
from .network import ServiceError,public_fetch,html_job

from . import role_catalog,provider_connections,public_job_feeds as feeds,job_filters as filters
TECH=role_catalog.GROUPS['Tech & Data']
ALIASES=role_catalog.ALIASES
VERSION=role_catalog.VERSION+2000

def words(value):return re.findall(r'[^\W_]+',value.casefold(),re.UNICODE)
def title_match(title,query,levels=None):
    chosen=levels if levels is not None else ['internship','early_career']
    band=filters.career({'title':title})
    if band=='senior' or band=='mid_career' and 'mid_career' not in chosen:return False
    if isinstance(query,list):return any(title_match(title,q,chosen) for q in query)
    phrases=ALIASES.get(query.casefold(),[query]);title_words=set(words(title))
    return any(all(w in title_words for w in words(p) if w not in {'junior','entry','level','new','grad','intern','internship','jobs','position'}) for p in phrases)

def blocked_url(value):
    host=(urlparse(value).hostname or '').lower()
    return host=='indeed.com' or host.endswith('.indeed.com') or host.startswith('indeed.') or '.indeed.' in host or host=='indeedjobs.com' or host.endswith('.indeedjobs.com')

def review(job,request):
    text=job.get('description','');issues=[];uncertain=[]
    if job.get('country') and not x.in_us(job):return None
    if not x.in_us(job):
        if job.get('location') and re.search(r'\b(?:United Kingdom|Canada|Australia|Germany|France|India|London|Singapore|Ireland|Israel|Tel Aviv|Poland|Warsaw|Brazil|Mexico|Japan|Tokyo|China|Shanghai|Beijing|Netherlands|Amsterdam|Spain|Madrid|Italy|Milan|Sweden|Stockholm|Switzerland|Zurich|New Zealand|Romania|Bucharest|Bengaluru|Bangalore|Toronto|Vancouver|Seoul|Korea|Philippines|Manila|Taiwan|Taipei|Hong Kong|Montreal|Montréal|Ottawa|Calgary|British Columbia|Ontario|Quebec|Viet Nam|Vietnam|Thailand|Bangkok|Malaysia|Kuala Lumpur|Turkey|Türkiye|Istanbul|Ukraine|Kyiv|Argentina|Buenos Aires|Chile|Santiago|Colombia|Bogot[aá]|Peru|Lima|Costa Rica|San Jos[eé], Costa Rica|Hungary|Budapest|Austria|Vienna|Belgium|Brussels|Norway|Oslo|Finland|Helsinki|Egypt|Cairo|Saudi Arabia|Riyadh|Qatar|Doha|Kenya|Nairobi|Ghana|Accra|Greece|Athens|Croatia|Serbia|Belgrade|Bulgaria|Sofia|Lithuania|Latvia|Estonia|Europe|EMEA|APAC|Dubai|United Arab Emirates|Portugal|Lisbon|Czech|Prague|Denmark|Copenhagen|South Africa|Nigeria|Pakistan|Bangladesh|Indonesia|Jakarta)\b',job['location'],re.I):return None
        issues.append('US work location not established')
    location_match=filters.location(job,request)
    if location_match is False:return None
    if location_match is None:issues.append('Requested location needs review');uncertain.append('Location not confirmed')
    pay_match=filters.pay(job,request)
    if pay_match is False:return None
    if pay_match is None:uncertain.append('Pay not confirmed for the requested minimum')
    if request.workplace!='any' and job.get('workplace')!=request.workplace:
        if job.get('workplace')!='unknown':return None
        issues.append('Work arrangement not stated');uncertain.append('Work arrangement not confirmed')
    band=filters.career(job);intern=band=='internship'
    if band=='senior' or band!='unknown' and band not in filters.levels(request):return None
    if band=='unknown' and set(filters.levels(request))!=set(filters.ALL):uncertain.append('Career level not confirmed')
    employment=job.get('employment_type','').casefold().replace('_','').replace('-','').replace(' ','')
    if not intern and 'any' not in request.job_types and employment in ('parttime','contract','temporary'):return None
    if not intern and employment not in ('fulltime','permanent'):issues.append('Full-time employment type not established')
    required=re.findall(r'[^.!?\n]{0,100}\b(?:\d+\s*(?:[-–]\s*\d+)?\+?\s+years?)[^.!?\n]{0,100}',text,re.I)
    years=[int(m[0]) for line in required if not re.search(r'preferred|desired|nice to have',line,re.I) and re.search(r'requir|minimum|at least',line,re.I) for m in re.findall(r'(\d+)\s*(?:[-–]\s*(\d+))?\+?\s+years?',line,re.I)]
    if intern and years and min(years)>=4:return None
    if not required and not intern:issues.append('Required experience not established')
    eligibility=re.findall(r'[^.!?\n]{0,80}(?:enroll|graduat|bachelor|master|Ph\.?D|citizen|sponsor)[^.!?\n]{0,160}',text,re.I)[:5]
    if not eligibility:issues.append('Student or degree requirements not stated')
    salary=job.get('salary')
    if isinstance(salary,dict):salary=salary.get('scrapeableCompensationSalarySummary') or salary.get('compensationTierSummary')
    job['salary']=salary or 'Not stated'
    if job['salary']=='Not stated':issues.append('Salary not stated')
    if job.get('workplace','unknown')=='unknown' and 'Work arrangement not stated' not in issues:issues.append('Work arrangement not stated')
    if job.get('description_incomplete'):issues.append('Provider supplies a description snippet; review the full posting before tailoring')
    published=x.parse_date(job.get('published_at'));added=x.parse_date(job.get('source_added_at'))
    stamp=published or added
    if stamp and not timedelta(0)<=datetime.now(timezone.utc)-stamp<=timedelta(days=request.days):return None
    if not stamp:issues.append('Listing date not verified');uncertain.append('Posting date not confirmed')
    if not x.in_us(job):uncertain.append('US location not confirmed')
    job.update(hard_filter_status='uncertain' if uncertain else 'matches',filter_reasons=uncertain,career_level=band)
    job.update(review_reasons=issues,review_status='needs_review' if issues else 'matches_preferences',experience_requirements=required[:4],eligibility_passages=eligibility,job_type='internship' if intern else 'full_time_or_unspecified',date_status='recent' if published else 'aggregator' if added else 'unknown',date_kind='republished' if published and (job.get('publication_source') or '').startswith('Ashby') else 'published' if published else 'aggregator_added' if added else 'unknown')
    return job

async def adzuna(user,query,location,*,trial=False):
    secret=provider_connections.resolve(user,manual=trial)
    if not secret:raise ServiceError('Adzuna is not enabled for regular searches on this account. Configure it in Settings; trial connections are test-only.')
    result=[]
    for page in ((1,) if trial else (1,2)):
        params={'app_id':secret['app_id'],'app_key':secret['app_key'],'what':query,'results_per_page':25,'sort_by':'date'}
        if not job_locations.region(location) and job_locations.provider_location(location):params['where']=job_locations.provider_location(location)
        data=await x.fetch_json(f'https://api.adzuna.com/v1/api/jobs/us/search/{page}',params)
        for item in data.get('results',[]):
            salary=' – '.join(str(item[k]) for k in ('salary_min','salary_max') if item.get(k) is not None)
            result.append(x.normalize_job('adzuna',item.get('title'),(item.get('company') or {}).get('display_name'),(item.get('location') or {}).get('display_name'),item.get('description'),item.get('redirect_url',''),source_identity='adzuna:'+str(item.get('id')),origin_key='adzuna',source_added_at=item.get('created'),country='US',locations=[{'location':str(v),'state':str(v) if v in job_locations.STATES.values() else ''} for v in (item.get('location') or {}).get('area',[]) if isinstance(v,str) and (v in job_locations.STATES.values() or v in job_locations.STATES)],salary_details={'minimum':item.get('salary_min',0),'maximum':item.get('salary_max',0),'currency':'USD','period':'year','estimated':item.get('salary_is_predicted') in (True,1,'1')},description_incomplete=True,employment_type=item.get('contract_time',''),salary=salary+(' (provider estimate)' if item.get('salary_is_predicted') in (True,1,'1') else '') if salary else 'Not stated'))
        if len(data.get('results',[]))<25:break
    return result

async def usajobs(query,location):
    if not(config.USAJOBS_KEY and config.USAJOBS_EMAIL):raise ServiceError('USAJOBS needs an API key and registered API email on the server.')
    result=[]
    for page in (1,2):
        params={'Keyword':query,'ResultsPerPage':25,'Page':page,'Fields':'Full'}
        if job_locations.provider_location(location):params['LocationName']=job_locations.provider_location(location)
        data=await x.fetch_json('https://data.usajobs.gov/api/search',params,{'Host':'data.usajobs.gov','User-Agent':config.USAJOBS_EMAIL,'Authorization-Key':config.USAJOBS_KEY})
        items=data.get('SearchResult',{}).get('SearchResultItems',[])
        for item in items:
            v=item['MatchedObjectDescriptor'];details=v.get('UserArea',{}).get('Details',{});locations=v.get('PositionLocation',[])
            if locations and not any(l.get('CountryCode') in ('United States','US','USA') for l in locations):continue
            text='\n'.join(str(details.get(k) or '') for k in ('JobSummary','MajorDuties','Education','Requirements','Qualifications'))+'\n'+str(v.get('QualificationSummary') or '')
            pay=v.get('PositionRemuneration',[])
            result.append(x.normalize_job('usajobs',v.get('PositionTitle'),v.get('OrganizationName'),v.get('PositionLocationDisplay'),text,v.get('PositionURI'),source_identity='usajobs:'+str(item.get('MatchedObjectId')),origin_key='usajobs',published_at=v.get('PublicationStartDate'),publication_source='USAJOBS PublicationStartDate',country='US',locations=[{'location':l.get('LocationName',''),'state':l.get('CountrySubDivisionCode','')} for l in locations if l.get('CountryCode') in ('United States','US','USA')],salary='; '.join(' – '.join(str(p.get(k,'')) for k in ('MinimumRange','MaximumRange'))+' '+p.get('Description','') for p in pay) or 'Not stated',deadline=v.get('ApplicationCloseDate'),employment_type=' '.join(str(s.get('Name','')) for s in v.get('PositionSchedule',[])),hiring_paths=details.get('HiringPath',[]),workplace='remote' if details.get('RemoteIndicator') is True else 'unknown'))
        if len(items)<25:break
    return result

async def discover(user,request,*,execution='manual'):
    queries=request.interests or [request.title];chosen_levels=filters.levels(request);boards=feeds.catalog_boards(user)
    if request.employer_boards is not None:boards=[b for b in boards if feeds.board_key(b) in request.employer_boards]
    trial_meta={'roles':[],'attempted_requests':0,'cached':False}
    info=provider_connections.public(user)
    trial=info['configured'] and info.get('usage')=='manual_trial'
    async def trial_search():
        if execution!='manual' or not provider_connections.trial_owner(user):
            statuses.append({'source':'adzuna','status':'disabled','message':'Trial excluded from daily and background searches.'});return
        requested=request.trial_roles if request.trial_roles is not None else queries[:2]
        roles=[q for q in queries if any(q.casefold()==r.casefold() for r in requested)][:2]
        if not roles:
            statuses.append({'source':'adzuna','status':'setup','message':'Select up to two trial roles from your search interests.'});return
        token=request.request_token or db.uid()
        for role in roles:
            if not provider_connections.claim_attempt(user,token,role):continue
            trial_meta['roles'].append(role);trial_meta['attempted_requests']+=1
            try:
                jobs.extend(await adzuna(user,ALIASES.get(role.casefold(),[role])[0],'United States' if request.locations else request.location,trial=True))
            except ServiceError as error:
                statuses.append({'source':'adzuna','status':'error','message':'Adzuna trial request failed. Check the account connection and provider allowance in Settings. Other sources are retained.'})
                break # Never retry or consume a second call after a quota/auth/connection failure.
        if not any(v['source']=='adzuna' and v['status']=='error' for v in statuses):statuses.append({'source':'adzuna','status':'ok','message':f"Manual trial checked {', '.join(trial_meta['roles']) or 'no additional roles (duplicate request)'}. {trial_meta['attempted_requests']} request(s) attempted; no pagination or retries."})
    jobs=[];statuses=[];usage=[];sem=asyncio.Semaphore(6);stopped=set()
    async def collect(label,fn):
        async with sem:
            if label in stopped:return
            try:
                rows=await asyncio.wait_for(fn(),60);jobs.extend(rows);statuses.append({'source':label,'status':'ok' if rows else 'empty','message':f'{len(rows)} results before preference checks. Source pages are bounded; this is not a complete market index.'})
            except (ServiceError,asyncio.TimeoutError) as e:
                if any(code in str(e) for code in ('HTTP 401','HTTP 403','HTTP 429')):stopped.add(label)
                statuses.append({'source':label,'status':'error','message':str(e) if isinstance(e,ServiceError) else 'Source timed out. Retry later; other results are retained.'})
    task_progress.stage('searching_jobs')
    calls=[]
    async def board_search(board):
        label=feeds.board_key(board)
        async with sem:
            try:
                rows,meta=await asyncio.wait_for(feeds.employer(board,refresh=request.refresh),60)
                jobs.extend(v for v in rows if title_match(v.get('title',''),queries,chosen_levels))
                statuses.append({'source':label,'status':'stale' if meta['stale'] else 'ok' if rows else 'empty','last_success':meta['last_success'],'snapshot_revision':meta['revision'],'message':f"{board['company']}: {len(rows)} public postings; {'cached' if meta['cached'] else 'refreshed'}. "+meta['error']})
            except (ServiceError,asyncio.TimeoutError):statuses.append({'source':label,'status':'error','message':board['company']+': public feed unavailable. Other sources are retained.'})
    async def community_search():
        async with sem:
            try:
                rows,meta=await feeds.community(refresh=request.refresh,queries=queries,levels=chosen_levels);jobs.extend(rows)
                statuses.append({'source':'github:open-jobs-data','status':'stale' if meta['stale'] else 'ok' if rows else 'empty','last_success':meta['last_success'],'snapshot_at':meta['snapshot_at'],'message':f"open-jobs-data: {len(rows)} community metadata records. Employer requirements require review. "+meta['error']})
            except (ServiceError,asyncio.TimeoutError):statuses.append({'source':'github:open-jobs-data','status':'error','message':'Community snapshot unavailable; other sources are retained.'})
    for source in dict.fromkeys(request.sources):
        if source in ('greenhouse','ashby','lever'):
            chosen=[b for b in boards if b['provider']==source]
            if not chosen:statuses.append({'source':source,'status':'setup','message':'No employer boards selected for this source.'})
            for board in chosen:calls.append(board_search(board))
        elif source=='github':calls.append(community_search())
        elif source in ('adzuna','usajobs'):
            if source=='adzuna' and trial:
                calls.append(trial_search());continue
            ready=bool(info['configured'] and info.get('usage')=='regular') if source=='adzuna' else bool(config.USAJOBS_KEY and config.USAJOBS_EMAIL)
            if not ready:
                statuses.append({'source':source,'status':'setup','message':('Adzuna needs an account connection enabled for searches. Test-only keys are excluded.' if source=='adzuna' else 'USAJOBS needs the shared connection configured.')});continue
            for query in queries:
                term=ALIASES.get(query.casefold(),[query])[0]
                calls.append(collect(source,lambda s=source,q=term:(adzuna(user,q,'United States' if request.locations else request.location) if s=='adzuna' else usajobs(q,'United States' if request.locations else request.location))))
        elif source=='jobspy':statuses.append({'source':'jobspy','status':'disabled','message':'Experimental scraping is retired. Indeed is excluded.'})
    await asyncio.gather(*calls)
    if 'web' in request.sources:
        if not config.ENABLE_WEB_SEARCH:statuses.append({'source':'web','status':'disabled','message':'AI web expansion is disabled.'})
        else:
            try:
                rows,meta=await ai.web_jobs('; '.join(queries)+'; career levels: '+', '.join(chosen_levels)+(('; minimum USD '+str(request.minimum_salary)+' per '+request.pay_period) if request.minimum_salary is not None else ''),'; '.join(request.locations) if request.locations else request.location,request.mode);usage+=meta
                for v in rows:
                    if blocked_url(v['url']):continue
                    job=x.normalize_job('openai_web',v['title'],v['company'],'',v['description'],v['url'],origin_key='web')
                    try:
                        page=await public_fetch(v['url'],2*1024*1024)
                        if blocked_url(page['url']) or page['status'] in (404,410):continue
                        if page['status']==200 and 'html' in page['content_type']:
                            info=html_job(page['content']);job.update({k:info[k] for k in ('description','location','country','workplace','published_at') if info.get(k)})
                            if info.get('published_at'):job['publication_source']='Employer page datePosted'
                    except ServiceError:pass
                    jobs.append(job)
                statuses.append({'source':'web','status':'ok','message':f'{len(rows)} cited AI results checked; usage is charged to your account key.'})
            except ServiceError as e:statuses.append({'source':'web','status':'error','message':str(e)})
    task_progress.stage('checking_jobs')
    candidates=[];excluded=0
    for job in x.deduplicate(jobs):
        if execution!='manual' and job.get('snapshot_stale'):continue
        if blocked_url(job['url']) or not title_match(job['title'],queries,chosen_levels):continue
        if not review(job,request):excluded+=1;continue
        candidates.append(job)
    candidates.sort(key=lambda j:(j.get('published_at') or j.get('source_added_at') or '',j['title'],j['url']),reverse=True)
    total=len(candidates)
    existing=db.list_entities(user,'job');records=[]
    by_identity={r['data'].get('source_identity'):r for r in existing if r['data'].get('source_identity')}
    application_jobs={r['data'].get('job_id') for r in db.list_entities(user,'application')}
    ranked=sorted(existing,key=lambda r:(r['id'] in application_jobs,r['data'].get('interest_state')=='saved',r['data'].get('interest_state')=='dismissed'))
    by_url={x.posting_key(r['data'].get('url','')):r for r in ranked}
    from .resume_conversation import write
    stamp=db.now()
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        for job in feeds.balanced(candidates,limit=None):
            old=by_url.get(x.posting_key(job['url'])) or by_identity.get(job.get('source_identity'))
            if old:
                job['first_discovered_at']=old['data'].get('first_discovered_at',old['created_at'])
                if job.get('description_incomplete') and not old['data'].get('description_incomplete') and len(old['data'].get('description',''))>len(job['description']):job.update(description=old['data']['description'],description_incomplete=False)
            key=old['id'] if old else hashlib.sha256((user+':job:'+str(job.get('source_identity') or job['url'])).encode()).hexdigest()[:32]
            latest=c.execute("SELECT payload FROM entities WHERE user_id=? AND id=? AND kind='job'",(user,key)).fetchone()
            previous=json.loads(latest['payload']) if latest else {}
            for field in ('interest_state','interest_updated_at'):
                if field in previous:job[field]=previous[field]
            write(c,user,'job',job,key)
            records.append({'id':key,'kind':'job','created_at':old['created_at'] if old else stamp,'updated_at':stamp,'data':job})
    return {'version':VERSION,'jobs':records,'sources':statuses,'ai_calls':usage,'checked_at':db.now(),'query':request.model_dump(exclude={'refresh','request_token'}),'excluded_unverified_us':excluded,'bounded_results':True,'total_matches':total,'retained_matches':len(records),'truncated':False,'limit':None,'page_size':25,'catalog_revision':feeds.REVISION,'adzuna_trial':trial_meta if trial else None}
