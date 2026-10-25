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
        async with httpx.AsyncClient(timeout=15,trust_env=False) as client:
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
            'url':url if source=='adzuna' and canonical_url(url) else canonical_url(url),'sources':[{'provider':source,'url':url,'checked_at':db.now()}],
            'published_at':None,'updated_at':None,'source_added_at':None,'publication_source':None,
            'first_discovered_at':db.now(),'last_checked_at':db.now(),'workplace':'unknown','country':'',
            'observations':[],**kwargs}

def deduplicate(jobs):
    merged={}
    for job in jobs:
        if not job.get('url'):continue
        key=job.get('source_identity') or canonical_url(job['url'])
        existing=merged.get(key) or next((v for v in merged.values() if canonical_url(v['url'])==canonical_url(job['url'])),None)
        if existing:
            existing['sources'] += [x for x in job['sources'] if x not in existing['sources']]
            if len(job['description'])>len(existing['description']):existing['description']=job['description']
        else:merged[key]=job.copy()
    return list(merged.values())

def matches_title(title,query):
    from .job_search import title_match
    return title_match(title,query)

def in_us(job):
    country=job.get('country','').upper().strip()
    if country:return country in ('US','USA','UNITED STATES','UNITED STATES OF AMERICA')
    location=job.get('location','')
    return bool(re.search(r'United States|\bUSA\b|\bUS\b|U\.S\.|,\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b',location))

def location_matches(job,query):
    if query.lower().strip() in ('united states','us','usa','nationwide','remote'):return True
    return query.casefold() in job.get('location','').casefold()

async def board_jobs(board, query):
    provider=board['provider'];token=quote(board['board'],safe='')
    if provider=='lever':
        host='api.eu.lever.co' if board.get('region')=='eu' else 'api.lever.co'
        rows=await fetch_json(f'https://{host}/v0/postings/{token}',{'mode':'json','limit':100})
        return [normalize_job('lever',v.get('text'),board['company'],v.get('categories',{}).get('location'),v.get('descriptionPlain','')+' '+ ' '.join(BeautifulSoup(x.get('content',''),'html.parser').get_text(' ',strip=True) for x in v.get('lists',[])),v.get('hostedUrl') or v.get('applyUrl'),source_identity='lever:'+token+':'+str(v.get('id')),origin_key='lever:'+token,workplace={'remote':'remote','hybrid':'hybrid','on-site':'onsite'}.get(v.get('workplaceType'),'unknown'),employment_type=v.get('categories',{}).get('commitment','')) for v in rows if matches_title(v.get('text',''),query)][:50]
    if provider=='greenhouse':
        url=f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs'
        payload=await fetch_json(url,{'content':'true'})
        result=[]
        for item in payload.get('jobs',[]):
            if not matches_title(item.get('title',''),query): continue
            job=normalize_job(provider,item.get('title'),board['company'],(item.get('location') or {}).get('name'),item.get('content',''),item.get('absolute_url',''),source_identity='greenhouse:'+token+':'+str(item.get('id')),origin_key='greenhouse:'+token,updated_at=item.get('updated_at'),observations=['Listed on the employer Greenhouse board at '+db.now()])
            loc=job['location'].lower()
            job['workplace']='remote' if 'remote' in loc else 'hybrid' if 'hybrid' in loc else 'unknown'
            # An update timestamp is never substituted for first publication.
            if len(result)<4 and str(item.get('id','')).isdigit():
                try:
                    detail=await fetch_json(url+'/'+str(item['id']))
                    if parse_date(detail.get('first_published')):
                        job['published_at']=detail['first_published'];job['publication_source']='Greenhouse first_published'
                except ServiceError: pass
            result.append(job)
            if len(result)>=20: break
        return result
    payload=await fetch_json(f'https://api.ashbyhq.com/posting-api/job-board/{token}',{'includeCompensation':'true'})
    result=[]
    for item in payload.get('jobs',[]):
        if item.get('isListed') is False or not matches_title(item.get('title',''),query): continue
        address=(item.get('address') or {}).get('postalAddress') or {}
        result.append(normalize_job('ashby',item.get('title'),board['company'],item.get('location'),item.get('descriptionPlain') or item.get('descriptionHtml'),item.get('jobUrl') or item.get('applyUrl'),source_identity='ashby:'+token+':'+str(item.get('id') or item.get('jobUrl')),origin_key='ashby:'+token,employment_type=item.get('employmentType',''),salary=item.get('compensation',{}),published_at=item.get('publishedAt'),publication_source='Ashby last publishedAt' if parse_date(item.get('publishedAt')) else None,country=address.get('addressCountry',''),workplace={'Remote':'remote','Hybrid':'hybrid','OnSite':'onsite'}.get(item.get('workplaceType'),'remote' if item.get('isRemote') else 'unknown'),observations=['Listed on the employer Ashby board at '+db.now()]))
        if len(result)>=20: break
    return result

async def adzuna_jobs(query,location,*,user=None):
    from .job_search import adzuna
    if not user:raise ServiceError('Adzuna requires an account connection.')
    return await adzuna(user,query,location)

async def discover(user,request):
    from .job_search import discover as search
    return await search(user,request)
