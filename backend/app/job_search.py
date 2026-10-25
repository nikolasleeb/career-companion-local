"""Public source search and account-owned decisions. No provider keys enter records."""
import asyncio,hashlib,json,re
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse
from . import config,db,integrations as x,task_progress,ai,job_locations
from .network import ServiceError,public_fetch,html_job

TECH=['Software engineering','IT and systems','Cloud infrastructure','Data science','Data engineering','Data analysis','Technical solutions']
ALIASES={
 'software engineering':['software engineer','software developer','application developer','computer science'],
 'it and systems':['IT support','IT specialist','information technology','systems engineer','systems administrator','network engineer','help desk','support engineer'],
 'cloud infrastructure':['cloud','infrastructure','devops','site reliability'],
 'data science':['data science','data scientist','machine learning','AI engineer'],
 'data engineering':['data engineer','data engineering','data platform','analytics engineer','ETL'],
 'data analysis':['data analyst','data analytics','business intelligence','business analyst','product analyst'],
 'technical solutions':['solutions engineer','integration','technical consultant','technical support'],
 'data analyst':['data analyst','data analytics','business intelligence analyst'],
}
VERSION=3

def words(value):return re.findall(r'[^\W_]+',value.casefold(),re.UNICODE)
def title_match(title,query):
    if re.search(r'\b(senior|sr\.?|principal|director|head of)\b',title,re.I) or re.search(r'\bstaff\b.*\b(engineer|scientist)\b',title,re.I) or (re.search(r'\blead\b',title,re.I) and not re.search(r'\blead generation\b',title,re.I)):return False
    if isinstance(query,list):return any(title_match(title,q) for q in query)
    phrases=ALIASES.get(query.casefold(),[query])
    title_words=set(words(title))
    return any(all(w in title_words for w in words(p) if w not in {'junior','entry','level','new','grad','intern','internship','jobs','position'}) for p in phrases)

def blocked_url(value):
    host=(urlparse(value).hostname or '').lower()
    return host=='indeed.com' or host.endswith('.indeed.com') or host.startswith('indeed.') or '.indeed.' in host or host=='indeedjobs.com' or host.endswith('.indeedjobs.com')

def review(job,request):
    text=job.get('description','');issues=[]
    if job.get('country') and not x.in_us(job):return None
    if not x.in_us(job):
        if job.get('location') and re.search(r'\b(?:United Kingdom|Canada|Australia|Germany|France|India|London|Singapore|Ireland)\b',job['location'],re.I):return None
        issues.append('US work location not established')
    location_match=job_locations.matches(job,request.location)
    if location_match is False:return None
    if location_match is None:issues.append('Requested location needs review')
    if request.workplace!='any' and job.get('workplace')!=request.workplace:
        if job.get('workplace')!='unknown':return None
        issues.append('Work arrangement not stated')
    intern=bool(re.search(r'\bintern(?:ship)?\b',job['title']+' '+job.get('employment_type',''),re.I))
    if intern and 'internship' not in request.job_types and 'any' not in request.job_types:return None
    if not intern and 'early_career' not in request.job_types and 'any' not in request.job_types:return None
    employment=job.get('employment_type','').casefold().replace('_','').replace('-','').replace(' ','')
    if not intern and 'any' not in request.job_types and employment in ('parttime','contract','temporary'):return None
    if not intern and employment not in ('fulltime','permanent'):issues.append('Full-time employment type not established')
    required=re.findall(r'[^.!?\n]{0,100}\b(?:\d+\s*(?:[-–]\s*\d+)?\+?\s+years?)[^.!?\n]{0,100}',text,re.I)
    years=[int(m[0]) for line in required if not re.search(r'preferred|desired|nice to have',line,re.I) and re.search(r'requir|minimum|at least',line,re.I) for m in re.findall(r'(\d+)\s*(?:[-–]\s*(\d+))?\+?\s+years?',line,re.I)]
    if 'any' not in request.job_types and years and min(years)>3 and not any(re.search(r'\bor\b|equivalent|in lieu',v,re.I) for v in required):return None
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
    if not stamp:issues.append('Listing date not verified')
    job.update(review_reasons=issues,review_status='needs_review' if issues else 'matches_preferences',experience_requirements=required[:4],eligibility_passages=eligibility,job_type='internship' if intern else 'full_time_or_unspecified',date_status='recent' if published else 'aggregator' if added else 'unknown',date_kind='republished' if published and (job.get('publication_source') or '').startswith('Ashby') else 'published' if published else 'aggregator_added' if added else 'unknown')
    return job

async def adzuna(query,location):
    if not(config.ADZUNA_ID and config.ADZUNA_KEY):raise ServiceError('Adzuna needs the server connection configured. Other sources can still search.')
    result=[]
    for page in (1,2):
        params={'app_id':config.ADZUNA_ID,'app_key':config.ADZUNA_KEY,'what':query,'results_per_page':25,'sort_by':'date'}
        if not job_locations.region(location) and job_locations.provider_location(location):params['where']=job_locations.provider_location(location)
        data=await x.fetch_json(f'https://api.adzuna.com/v1/api/jobs/us/search/{page}',params)
        for item in data.get('results',[]):
            salary=' – '.join(str(item[k]) for k in ('salary_min','salary_max') if item.get(k) is not None)
            result.append(x.normalize_job('adzuna',item.get('title'),(item.get('company') or {}).get('display_name'),(item.get('location') or {}).get('display_name'),item.get('description'),item.get('redirect_url',''),source_identity='adzuna:'+str(item.get('id')),origin_key='adzuna',source_added_at=item.get('created'),country='US',description_incomplete=True,employment_type=item.get('contract_time',''),salary=salary+(' (provider estimate)' if item.get('salary_is_predicted') in (True,1,'1') else '') if salary else 'Not stated'))
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

async def discover(user,request):
    queries=request.interests or [request.title];boards=[r['data'] for r in db.list_entities(user,'board')]
    jobs=[];statuses=[];usage=[];sem=asyncio.Semaphore(4);stopped=set()
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
    for source in dict.fromkeys(request.sources):
        if source in ('greenhouse','ashby','lever'):
            chosen=[b for b in boards if b['provider']==source][:8]
            if not chosen:statuses.append({'source':source,'status':'setup','message':'Add an employer career-page URL to search this source.'})
            for board in chosen:calls.append(collect(source+':'+board['board'],lambda b=board:x.board_jobs(b,queries)))
        elif source in ('adzuna','usajobs'):
            ready=bool(config.ADZUNA_ID and config.ADZUNA_KEY) if source=='adzuna' else bool(config.USAJOBS_KEY and config.USAJOBS_EMAIL)
            if not ready:
                statuses.append({'source':source,'status':'setup','message':source.upper()+' needs the shared server connection configured.'});continue
            for query in queries:
                # One bounded provider query per role interest, not one per alias.
                term=ALIASES.get(query.casefold(),[query])[0]
                calls.append(collect(source,lambda s=source,q=term:(x.adzuna_jobs(q,request.location) if s=='adzuna' else usajobs(q,request.location))))
        elif source=='jobspy':statuses.append({'source':'jobspy','status':'disabled','message':'Experimental scraping is retired. Indeed is excluded.'})
    await asyncio.gather(*calls)
    if 'web' in request.sources:
        if not config.ENABLE_WEB_SEARCH:statuses.append({'source':'web','status':'disabled','message':'AI web expansion is disabled.'})
        else:
            try:
                rows,meta=await ai.web_jobs('; '.join(queries),request.location,request.mode);usage+=meta
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
    existing=db.list_entities(user,'job');records=[];excluded=0
    for job in x.deduplicate(jobs):
        if blocked_url(job['url']) or not title_match(job['title'],queries):continue
        if not review(job,request):excluded+=1;continue
        old=next((r for r in existing if (job.get('source_identity') and r['data'].get('source_identity')==job['source_identity']) or x.canonical_url(r['data'].get('url',''))==x.canonical_url(job['url'])),None)
        if old:
            job['first_discovered_at']=old['data'].get('first_discovered_at',old['created_at'])
            for key in ('interest_state','interest_updated_at'):
                if key in old['data']:job[key]=old['data'][key]
            # Never replace a complete reviewed/imported posting with a snippet.
            if job.get('description_incomplete') and not old['data'].get('description_incomplete') and len(old['data'].get('description',''))>len(job['description']):job.update(description=old['data']['description'],description_incomplete=False)
        job['text_overlap']=[]
        from .resume_conversation import write
        key=old['id'] if old else hashlib.sha256((user+':job:'+str(job.get('source_identity') or job['url'])).encode()).hexdigest()[:32]
        with db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            latest=c.execute("SELECT payload FROM entities WHERE user_id=? AND id=? AND kind='job'",(user,key)).fetchone()
            if latest:
                previous=json.loads(latest['payload'])
                for field in ('interest_state','interest_updated_at'):
                    if field in previous:job[field]=previous[field]
            write(c,user,'job',job,key)
        records.append(db.get(user,key,'job'))
        if len(records)>=100:break
    records.sort(key=lambda r:(r['data']['review_status']=='matches_preferences',r['data'].get('published_at') or r['data'].get('source_added_at') or ''),reverse=True)
    return {'version':VERSION,'jobs':records,'sources':statuses,'ai_calls':usage,'checked_at':db.now(),'query':request.model_dump(exclude={'refresh'}),'excluded_unverified_us':excluded,'bounded_results':True}
