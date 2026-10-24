import asyncio
import json
import re
from urllib.parse import quote, urlparse, urlencode, parse_qsl, urlunparse
from datetime import datetime, timezone, timedelta
import httpx
from bs4 import BeautifulSoup
from . import config, db, ai
from .network import ServiceError, public_fetch, html_job

async def fetch_json(url, params=None, headers=None):
    try:
        async with httpx.AsyncClient(timeout=25,trust_env=False) as client:
            async with client.stream('GET',url,params=params,headers=headers) as response:
                if response.status_code>=400:
                    raise ServiceError(f'The source returned HTTP {response.status_code}. Retry later or check the source configuration.')
                raw=bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw)>12*1024*1024:
                        raise ServiceError('The source response exceeded the size limit.')
                try: return json.loads(raw)
                except ValueError: raise ServiceError('The source returned unreadable data.') from None
    except httpx.HTTPError:
        raise ServiceError('The source timed out or could not be reached.') from None

async def onet(path, params=None):
    if not config.ONET_KEY:
        raise ServiceError('Configure ONET_API_KEY on the server to load the official assessment. Your saved profile remains available.')
    return await fetch_json('https://api-v2.onetcenter.org/mnm/interestprofiler/'+path,params,{'X-API-Key':config.ONET_KEY,'Accept':'application/json'})

async def onet_questions():
    payload=await onet('questions_30',{'start':1,'end':30})
    questions=payload.get('question',[])
    options=payload.get('answer_option',payload.get('answer_options',[]))
    if len(questions)!=30 or {q.get('index') for q in questions}!=set(range(1,31)) or {o.get('value') for o in options}!={1,2,3,4,5}:
        raise ServiceError('The O*NET response did not contain the complete official assessment. Try again later.')
    return {'questions':questions,'options':options,'provider':'O*NET Interest Profiler Mini-IP','source':'https://services.onetcenter.org/ip'}

async def onet_results(answers, zone=None):
    if set(answers)!=set(str(i) for i in range(1,31)) or any(type(v)!=int or v not in range(1,6) for v in answers.values()):
        raise ServiceError('Answer all 30 questions with one of the five official response options.')
    encoded=''.join(str(answers[str(i)]) for i in range(1,31))
    score=await onet('results',{'answers':encoded})
    results=score.get('result',[])
    areas={'realistic','investigative','artistic','social','enterprising','conventional'}
    if {r.get('code') for r in results}!=areas or any(not isinstance(r.get('score'),int) for r in results):
        raise ServiceError('The official scoring response was incomplete. Your answers remain saved.')
    params={r['code']:r['score'] for r in results}
    params.update({'start':1,'end':20})
    if zone: params['zone']=zone
    careers=await onet('careers',params)
    return {'scores':results,'careers':careers.get('career',[]),'job_zone':zone,'answers':answers,'provider':'O*NET Interest Profiler Mini-IP','completed_at':db.now()}

def parse_date(value):
    if not value or not isinstance(value,str): return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError: return None

def recent(job, days=7, current=None):
    date=parse_date(job.get('published_at'))
    current=current or datetime.now(timezone.utc)
    return bool(date and timedelta(0)<=current-date<=timedelta(days=days) and job.get('publication_source'))

def canonical_url(url):
    try:
        p=urlparse(url)
        if p.scheme not in ('https','http') or not p.netloc or p.username or p.password: return ''
        params=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('source','ref','referral','gh_src')]
        return urlunparse((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),'',urlencode(sorted(params)),''))
    except ValueError: return ''

def normalize_job(source,title,company,location,description,url,**kwargs):
    return {'title':str(title or '')[:250],'company':str(company or '')[:250],'location':str(location or '')[:300],
            'description':BeautifulSoup(str(description or ''),'html.parser').get_text(' ',strip=True)[:100000],
            'url':canonical_url(url),'sources':[{'provider':source,'url':url,'checked_at':db.now()}],
            'published_at':None,'updated_at':None,'source_added_at':None,'publication_source':None,
            'first_discovered_at':db.now(),'last_checked_at':db.now(),'workplace':'unknown','country':'',
            'observations':[],**kwargs}

def deduplicate(jobs):
    merged={}
    role_keys={}
    for job in jobs:
        if not job.get('url'): continue
        key=job['url']
        role='|'.join(re.sub(r'\W+','',job.get(k,'').casefold()) for k in ('company','title','location'))
        key=key if key in merged else role_keys.get(role,key)
        if key in merged:
            existing=merged[key]
            existing['sources'] += [s for s in job['sources'] if s['url'] not in {x['url'] for x in existing['sources']}]
            if len(job['description'])>len(existing['description']): existing['description']=job['description']
            if not existing.get('published_at') and job.get('published_at'):
                for field in ('published_at','publication_source'): existing[field]=job[field]
            existing['observations']=list(dict.fromkeys(existing['observations']+job['observations']))
        else:
            merged[key]=job.copy();role_keys[role]=key
    return list(merged.values())

def matches_title(title, query):
    if re.search(r'\b(senior|sr\.?|staff|principal|director|head of|lead)\b',title,re.I): return False
    tokens=[t for t in re.findall(r'[a-z]+',query.lower()) if t not in ('junior','entry','level','new','grad','intern','internship','jobs','position')]
    return all(t in title.lower() for t in tokens) if tokens else True

def in_us(job):
    country=job.get('country','').upper()
    if country: return country in ('US','USA','UNITED STATES','UNITED STATES OF AMERICA')
    location=job.get('location','')
    if re.search(r'United States|\bUSA\b|\bUS\b|U\.S\.',location): return True
    if re.search(r',\s*(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b',location): return True
    return bool(re.search(r'United States|\bUSA\b|\bUS[- ]based\b|\bU\.S\.',job.get('description','')))

def location_matches(job, query):
    if query.lower().strip() in ('united states','us','usa','nationwide','remote'): return True
    return query.lower() in job.get('location','').lower() or job.get('workplace')=='remote'

async def board_jobs(board, query):
    provider=board['provider'];token=quote(board['board'],safe='')
    if provider=='greenhouse':
        url=f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs'
        payload=await fetch_json(url,{'content':'true'})
        result=[]
        for item in payload.get('jobs',[]):
            if not matches_title(item.get('title',''),query): continue
            job=normalize_job(provider,item.get('title'),board['company'],(item.get('location') or {}).get('name'),item.get('content',''),item.get('absolute_url',''),updated_at=item.get('updated_at'),observations=['Listed on the employer Greenhouse board at '+db.now()])
            loc=job['location'].lower()
            job['workplace']='remote' if 'remote' in loc else 'hybrid' if 'hybrid' in loc else 'unknown'
            # An update timestamp is never substituted for first publication.
            if len(result)<12 and str(item.get('id','')).isdigit():
                try:
                    detail=await fetch_json(url+'/'+str(item['id']))
                    if parse_date(detail.get('first_published')):
                        job['published_at']=detail['first_published'];job['publication_source']='Greenhouse first_published'
                except ServiceError: pass
            result.append(job)
            if len(result)>=20: break
        return result
    payload=await fetch_json(f'https://api.ashbyhq.com/posting-api/job-board/{token}')
    result=[]
    for item in payload.get('jobs',[]):
        if item.get('isListed') is False or not matches_title(item.get('title',''),query): continue
        address=(item.get('address') or {}).get('postalAddress') or {}
        result.append(normalize_job('ashby',item.get('title'),board['company'],item.get('location'),item.get('descriptionPlain') or item.get('descriptionHtml'),item.get('jobUrl') or item.get('applyUrl'),published_at=item.get('publishedAt'),publication_source='Ashby last publishedAt' if parse_date(item.get('publishedAt')) else None,country=address.get('addressCountry',''),workplace={'Remote':'remote','Hybrid':'hybrid','OnSite':'onsite'}.get(item.get('workplaceType'),'remote' if item.get('isRemote') else 'unknown'),observations=['Listed on the employer Ashby board at '+db.now()]))
        if len(result)>=20: break
    return result

async def adzuna_jobs(query,location):
    if not (config.ADZUNA_ID and config.ADZUNA_KEY): raise ServiceError('Configure ADZUNA_APP_ID and ADZUNA_APP_KEY to enable this optional source.')
    payload=await fetch_json('https://api.adzuna.com/v1/api/jobs/us/search/1',{'app_id':config.ADZUNA_ID,'app_key':config.ADZUNA_KEY,'what':query,'where':location,'results_per_page':20,'sort_by':'date'})
    # Adzuna creation time is retained as an aggregator date, not verified employer publication.
    return [normalize_job('adzuna',item.get('title'),(item.get('company') or {}).get('display_name'),(item.get('location') or {}).get('display_name'),item.get('description'),item.get('redirect_url',''),source_added_at=item.get('created'),country='US') for item in payload.get('results',[])]

def jobspy_sync(query,location):
    import multiprocessing
    from pathlib import Path
    import subprocess, sys, tempfile
    # A child process provides a hard timeout; blocked libraries cannot hold the
    # account's discovery slot indefinitely. No credentials are passed to it.
    with tempfile.TemporaryDirectory(prefix='nextstep-jobs-') as folder:
        output=Path(folder)/'jobs.json'
        script='''import json,sys\nfrom jobspy import scrape_jobs\njobs=scrape_jobs(site_name=["linkedin","indeed","glassdoor"],search_term=sys.argv[1],location=sys.argv[2],country_indeed="USA",results_wanted=10,hours_old=168,verbose=0)\nrows=json.loads(jobs.to_json(orient="records",date_format="iso"))\nerrors=jobs.attrs.get("errors",{})\nwarnings=jobs.attrs.get("warnings",{})\nopen(sys.argv[3],"w").write(json.dumps({"rows":rows,"errors":errors,"warnings":warnings}))\n'''
        import os
        try:
            completed=subprocess.run([sys.executable,'-c',script,query,location,str(output)],timeout=45,capture_output=True,env={'PATH':os.defpath,'LANG':'C.UTF-8'})
        except subprocess.TimeoutExpired: raise ServiceError('The experimental scraper timed out. Other sources remain available.') from None
        if completed.returncode or not output.exists(): raise ServiceError('The experimental scraper is unavailable. Build with INSTALL_JOBSPY=true, or leave it disabled.')
        return json.loads(output.read_text())

async def discover(user, request):
    boards=[r['data'] for r in db.list_entities(user,'board')]
    jobs=[];statuses=[];usage=[]
    for source in request.sources:
        if source in ('greenhouse','ashby'):
            chosen=[b for b in boards if b['provider']==source]
            if not chosen: statuses.append({'source':source,'status':'setup','message':'Add an employer board in Sources.'})
            for board in chosen[:8]:
                try:
                    result=await board_jobs(board,request.title);jobs+=result
                    statuses.append({'source':source+':'+board['board'],'status':'ok' if result else 'empty','message':f'{len(result)} matching titles returned before location/date filters.'})
                except ServiceError as error:
                    statuses.append({'source':source+':'+board['board'],'status':'error','message':str(error)})
        elif source=='adzuna':
            try:
                result=await adzuna_jobs(request.title,request.location);jobs+=result
                statuses.append({'source':source,'status':'ok' if result else 'empty','message':f'{len(result)} listings returned; publication dates need verification.'})
            except ServiceError as error: statuses.append({'source':source,'status':'error','message':str(error)})
        elif source=='web':
            if not config.ENABLE_WEB_SEARCH:
                statuses.append({'source':source,'status':'disabled','message':'Web search is disabled in the server configuration.'});continue
            try:
                result,meta=await ai.web_jobs(request.title,request.location,request.mode);usage+=meta
                for item in result:
                    job=normalize_job('openai_web',item['title'],item['company'],'',item['description'],item['url'])
                    try:
                        page=await public_fetch(item['url'],2*1024*1024)
                        if page['status'] in (404,410): continue
                        if page['status']==200 and 'html' in page['content_type']:
                            detail=html_job(page['content'])
                            if detail['description']: job['description']=detail['description']
                            for field in ('location','country','workplace'):
                                if detail.get(field): job[field]=detail[field]
                            if parse_date(detail.get('published_at')):
                                job['published_at']=detail['published_at'];job['publication_source']='JobPosting datePosted at '+page['url']
                            if parse_date(detail.get('valid_through')) and parse_date(detail['valid_through'])<datetime.now(timezone.utc): continue
                            job['observations'].append('Public page returned HTTP 200 at '+db.now()+'; this does not establish hiring intent.')
                    except ServiceError: job['observations'].append('Application page could not be checked.')
                    jobs.append(job)
                statuses.append({'source':source,'status':'ok' if result else 'empty','message':f'{len(result)} cited search results returned.'})
            except ServiceError as error: statuses.append({'source':source,'status':'error','message':str(error)})
        elif source=='jobspy':
            if not config.ENABLE_JOBSPY:
                statuses.append({'source':source,'status':'disabled','message':'Optional experimental scraping is disabled.'});continue
            try:
                result=await asyncio.to_thread(jobspy_sync,request.title,request.location)
                for item in result['rows']:
                    jobs.append(normalize_job('jobspy:'+str(item.get('site','')),item.get('title'),item.get('company'),item.get('location'),item.get('description'),item.get('job_url_direct') or item.get('job_url') or '',source_added_at=item.get('date_posted')))
                statuses.append({'source':source,'status':'partial' if result['errors'] else 'ok','message':f'{len(result["rows"])} scraper records; check each board status.'})
                for name in result['errors']: statuses.append({'source':'jobspy:'+name,'status':'error','message':'This board failed or blocked the request. No bypass was attempted.'})
            except ServiceError as error: statuses.append({'source':source,'status':'error','message':str(error)})
    existing={canonical_url(r['data'].get('url','')):r for r in db.list_entities(user,'job') if r['data'].get('sources')}
    records=[];unknown_country=0
    experience=' '.join(ai.experience_text(r['data']) for r in db.list_entities(user,'experience') if r['data'].get('confirmed'))
    for job in deduplicate(jobs):
        if not matches_title(job['title'],request.title): continue
        if not in_us(job): unknown_country+=1;continue
        if not location_matches(job,request.location): continue
        if request.workplace!='any' and job.get('workplace')!=request.workplace: continue
        published=parse_date(job.get('published_at'))
        if published and not recent(job,request.days): continue
        job['date_status']='recent' if recent(job,request.days) else 'unknown'
        words=['SQL','Python','Excel','Tableau','Power BI','Git','Linux','Windows','networking','statistics']
        job['text_overlap']=[w for w in words if re.search(r'\b'+re.escape(w)+r'\b',experience,re.I) and re.search(r'\b'+re.escape(w)+r'\b',job['description'],re.I)]
        old=existing.get(job['url'])
        if old: job['first_discovered_at']=old['data'].get('first_discovered_at',old['created_at'])
        record=db.save(user,'job',job,old['id'] if old else None);records.append(record)
        if len(records)>=50: break
    records.sort(key=lambda r:(r['data']['date_status']=='recent',len(r['data']['text_overlap']),r['data'].get('published_at') or ''),reverse=True)
    return {'jobs':records,'sources':statuses,'ai_calls':usage,'checked_at':db.now(),'query':request.model_dump(exclude={'refresh'}),'excluded_unverified_us':unknown_country}
