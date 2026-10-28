"""Explicit, bounded adapters for curated official employer sources."""
import hashlib,json,re,time,asyncio
from datetime import datetime,timezone
from urllib.parse import urlsplit
from .network import ServiceError
ATS={'greenhouse','ashby','lever'}
REGISTRY={'greenhouse':'Greenhouse public board','ashby':'Ashby public board','lever':'Lever public board','official':'Curated official careers search'}

def query_key(board,request):
    query={'roles':sorted({v.casefold().strip() for v in (request.interests or [request.title])}),'location':request.location.casefold().strip(),'locations':sorted(request.locations),'levels':request.career_levels,'job_types':request.job_types}
    return 'official:'+board['board']+':'+hashlib.sha256(json.dumps(query,sort_keys=True).encode()).hexdigest()[:24]

async def jobs(board,request):
    if board['provider'] not in REGISTRY:raise ServiceError('No registered employer source.')
    if board['provider'] in ATS or board['provider']=='official' and board['board'] in ('amazon','apple','capitalone','intuit'):
        from .integrations import board_jobs
        return await board_jobs(board,request if board['provider']=='official' else None)
    raise ServiceError('This employer has no registered automated source. Open its official careers site.')

def posting_date(value):
    from .integrations import parse_date
    parsed=parse_date(value)
    if parsed:return parsed.isoformat()
    for fmt in ('%B %d, %Y','%b %d, %Y'):
        try:return datetime.strptime(' '.join(str(value).split()),fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:pass
    return None

def terms(request):
    from .role_catalog import ALIASES
    return dict.fromkeys(ALIASES.get(v.casefold(),[v])[0] for v in (request.interests or [request.title]))

async def amazon(request):
    from . import integrations as x
    rows={};deadline=time.monotonic()+40
    for term in terms(request):
        for page in range(2):
            if time.monotonic()>=deadline:return x.BoardRows(rows.values(),complete=False)
            try:
                payload=await x.fetch_json('https://www.amazon.jobs/en/search.json',{'base_query':term,'offset':page*100,'result_limit':100,'normalized_country_code[]':'USA','sort':'recent'},max_bytes=8*1024*1024)
            except (ServiceError,asyncio.TimeoutError):
                if rows:return x.BoardRows(rows.values(),complete=False)
                raise
            values=payload.get('jobs')
            if payload.get('error') or not isinstance(values,list):raise ServiceError('Amazon search did not return a valid jobs list.')
            for v in values:
                identity=str(v.get('id_icims') or v.get('id') or v.get('job_id') or '')
                path=v.get('job_path') or v.get('url_next_step') or ''
                if not identity or not v.get('title'):continue
                url=path if path.startswith('https://') else 'https://www.amazon.jobs'+path
                if urlsplit(url).hostname not in ('www.amazon.jobs','amazon.jobs') or not re.search(r'/jobs/\d+',url):url='https://www.amazon.jobs/en/jobs/'+identity
                location=', '.join(str(v.get(k) or '') for k in ('city','state','country_code') if v.get(k))
                text='\n'.join(str(v.get(k) or '') for k in ('description','basic_qualifications','preferred_qualifications'))
                rows[identity]=x.normalize_job('official',v['title'],'Amazon',location,text,url,source_identity='amazon:'+identity,origin_key='official:amazon',country=v.get('country_code',''),published_at=posting_date(v.get('posted_date_iso') or v.get('posted_date')),publication_source='Amazon posting date',employment_type=v.get('job_schedule_type',''),division=v.get('business_category',''),employer_id='amazon',description_incomplete=not bool(v.get('basic_qualifications')),observations=['Amazon public careers search; bounded query results, not a complete inventory.'])
            if len(values)<100:break
    return x.BoardRows(rows.values(),complete=False)

async def apple(request):
    from . import integrations as x
    from .network import public_fetch
    from urllib.parse import urlencode
    rows={};deadline=time.monotonic()+40
    for term in terms(request):
        for page in range(1,3):
            if time.monotonic()>=deadline:return x.BoardRows(rows.values(),complete=False)
            try:
                response=await public_fetch('https://jobs.apple.com/en-us/search?'+urlencode({'search':term,'location':'united-states-USA','page':page}),3*1024*1024)
            except (ServiceError,asyncio.TimeoutError):
                if rows:return x.BoardRows(rows.values(),complete=False)
                raise
            if response['status']!=200:raise ServiceError('Apple public search is unavailable.')
            match=re.search(r'window\.__staticRouterHydrationData\s*=\s*JSON.parse\(("(?:[^"\\]|\\.)*")\)',response['content'].decode('utf-8','replace') if isinstance(response['content'],bytes) else response['content'])
            if not match:raise ServiceError('Apple search data format changed. Other sources are retained.')
            try:payload=json.loads(json.loads(match.group(1)))['loaderData']['search'];values=payload['searchResults']
            except (ValueError,KeyError,TypeError):raise ServiceError('Apple search data is unavailable.') from None
            if not isinstance(values,list):raise ServiceError('Apple search returned an invalid jobs list.')
            for v in values:
                identity=str(v.get('id') or '')
                if not identity or not re.fullmatch(r'[A-Za-z0-9-]+',identity) or not v.get('postingTitle'):continue
                locations=v.get('locations') or [];us=any(a.get('countryID')=='iso-country-USA' for a in locations)
                location='; '.join(', '.join(str(a.get(k) or '') for k in ('name','stateProvince','countryName') if a.get(k)) for a in locations)
                rows[identity]=x.normalize_job('official',v['postingTitle'],'Apple',location,v.get('jobSummary',''),'https://jobs.apple.com/en-us/details/'+identity,source_identity='apple:'+identity,origin_key='official:apple',country='US' if us else '',published_at=posting_date(v.get('postDateInGMT') or v.get('postingDate')),publication_source='Apple posting date',employer_id='apple',description_incomplete=True,observations=['Apple public careers search summary. Review the full official posting for requirements; bounded query results.'])
            if len(values)==0 or page*20>=payload.get('totalRecords',100000):break
    return x.BoardRows(rows.values(),complete=False)

SITEMAPS={'capitalone':('www.capitalonecareers.com','Capital One','jobs_sitemap.xml'),'intuit':('jobs.intuit.com','Intuit','sitemap.xml')}
async def sitemap_jobs(board,request):
    """Read the advertised public sitemap and bounded JobPosting metadata, never search pages."""
    from . import integrations as x,job_search,job_filters
    from .network import public_fetch,html_job
    from bs4 import BeautifulSoup
    import xml.etree.ElementTree as ET
    from urllib.robotparser import RobotFileParser
    host,company,path=SITEMAPS[board];deadline=time.monotonic()+40
    policy=await public_fetch('https://'+host+'/robots.txt',128*1024)
    if policy['status'] not in (200,404):raise ServiceError('The official source access policy could not be checked.')
    robot=RobotFileParser();robot.parse(policy['content'].decode('utf-8','replace').splitlines() if policy['status']==200 else [])
    def allowed(url):return urlsplit(url).hostname==host and robot.can_fetch('NextStepCareerCoach',url)
    url='https://'+host+'/'+path
    if not allowed(url):raise ServiceError('The employer restricts automated sitemap access. Open its official careers site.')
    response=await public_fetch(url,6*1024*1024)
    if response['status']!=200:raise ServiceError('The official jobs sitemap is unavailable.')
    raw=response['content']
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ServiceError('Unsupported sitemap format.')
    try:tree=ET.fromstring(raw)
    except ET.ParseError:raise ServiceError('The official sitemap format changed.') from None
    queries=request.interests or [request.title];wanted=[]
    for node in tree.iter():
        link=node.text or ''
        if node.tag.endswith('loc') and '/job/' in link and allowed(link) and job_search.title_match(urlsplit(link).path.replace('-',' '),queries,job_filters.levels(request)):
            wanted.append(link)
    rows=[]
    for link in list(dict.fromkeys(wanted))[:8]:
        if len(rows)>=8 or time.monotonic()>=deadline:break
        try:
            detail=await public_fetch(link,3*1024*1024)
            if detail['status']!=200 or not allowed(detail.get('url',link)):continue
            soup=BeautifulSoup(detail['content'],'html.parser');structured=any('JobPosting' in s.get_text() for s in soup.find_all('script',type='application/ld+json'))
            if not structured:continue
            item=html_job(detail['content'])
            if not item.get('title') or not item.get('description') or item['title']=='Target opportunity':continue
            identity=link.rstrip('/').split('/')[-1]
            rows.append(x.normalize_job('official',item['title'],company,item.get('location',''),item['description'],link,source_identity=board+':'+identity,origin_key='official:'+board,employer_id=board,country=item.get('country',''),published_at=posting_date(item.get('published_at')),publication_source=company+' JobPosting date',deadline=item.get('valid_through'),workplace=item.get('workplace','unknown'),description_incomplete=False,observations=['Official careers sitemap and JobPosting metadata. Bounded matching pages; not a complete inventory.']))
        except (ServiceError,asyncio.TimeoutError):continue
    return x.BoardRows(rows,complete=False)
