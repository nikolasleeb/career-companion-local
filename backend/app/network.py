"""Public URL imports pin each connection to an address validated before connecting.

No ambient proxy credentials, cookies, private network access, or automatic redirects.
Provider API calls elsewhere use fixed, application-owned HTTPS base URLs.
"""
import asyncio
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlparse, urljoin, urlunparse
from bs4 import BeautifulSoup

class ServiceError(Exception):
    pass

def public_address(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if port not in (80,443):
            raise ValueError()
        host = parsed.hostname.encode('idna').decode('ascii')
        if host.lower().rstrip('.') in ('localhost','localhost.localdomain'):
            raise ValueError()
        addresses = {r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
        if not addresses or not all(ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError()
        return parsed, host, port, sorted(addresses)[0]
    except (ValueError, OSError, UnicodeError):
        raise ServiceError('Only public HTTP(S) URLs on ports 80 or 443 can be imported. Local and private addresses are blocked.') from None

def safe_fetch(url, max_bytes=10*1024*1024):
    original = url
    for _ in range(5):
        parsed, host, port, address = public_address(url)
        conn = (http.client.HTTPSConnection(host, port, timeout=12, context=ssl.create_default_context()) if parsed.scheme == 'https' else http.client.HTTPConnection(host, port, timeout=12))
        # http.client still uses the original hostname for TLS SNI and certificate
        # verification, while socket creation is pinned to the validated address.
        conn._create_connection = lambda addr, timeout=12, source_address=None, **kwargs: socket.create_connection((address, port), timeout, source_address)
        path = urlunparse(('', '', parsed.path or '/', parsed.params, parsed.query, ''))
        try:
            conn.request('GET', path, headers={'User-Agent':'NextStepCareerCoach/1.0', 'Accept-Encoding':'identity', 'Accept':'text/html,application/json,text/plain,application/pdf'})
            response = conn.getresponse()
            status = response.status
            if status in (301,302,303,307,308):
                redirect = response.getheader('Location')
                if not redirect:
                    raise ServiceError('The page redirected without a destination.')
                url = urljoin(url, redirect)
                continue
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ServiceError('This page is too large to import.')
            return {'status':status,'content':content,'content_type':response.getheader('Content-Type',''),'url':url,'original_url':original}
        except (OSError, http.client.HTTPException):
            raise ServiceError('The public page could not be reached. Paste its description instead.') from None
        finally:
            conn.close()
    raise ServiceError('This page has too many redirects. Paste its description instead.')

async def public_fetch(url, max_bytes=10*1024*1024):
    return await asyncio.to_thread(safe_fetch, url, max_bytes)

def html_job(content):
    soup = BeautifulSoup(content, 'html.parser')
    found = []
    def walk(value):
        if isinstance(value, list):
            for item in value: walk(item)
        if isinstance(value, dict):
            types = value.get('@type', [])
            if types == 'JobPosting' or (isinstance(types,list) and 'JobPosting' in types):
                found.append(value)
            if '@graph' in value: walk(value['@graph'])
    for script in soup.find_all('script', type='application/ld+json'):
        try: walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError): pass
    if found:
        job = found[0]
        hiring = job.get('hiringOrganization') or {}
        locations = job.get('jobLocation') or []
        if isinstance(locations, dict): locations = [locations]
        addresses = [loc.get('address', {}) for loc in locations if isinstance(loc, dict)]
        addresses = [a for a in addresses if isinstance(a, dict)]
        countries = [a.get('addressCountry', '') for a in addresses]
        countries = [c.get('name', '') if isinstance(c, dict) else str(c) for c in countries]
        location = '; '.join(', '.join(str(a[k]) for k in ('addressLocality', 'addressRegion', 'addressCountry') if isinstance(a.get(k), str)) for a in addresses)
        eligible = job.get('applicantLocationRequirements') or []
        if isinstance(eligible, dict): eligible = [eligible]
        eligible_names = [str(a.get('name', '')) for a in eligible if isinstance(a, dict)]
        location = '; '.join(x for x in [location, ', '.join(eligible_names)] if x)

        return {'title':str(job.get('title','Target opportunity'))[:250],
                'company':str(hiring.get('name','') if isinstance(hiring,dict) else '')[:250],
                'description':BeautifulSoup(str(job.get('description','')), 'html.parser').get_text(' ',strip=True)[:100000],
                'published_at':job.get('datePosted'), 'valid_through':job.get('validThrough'),
                'location':location[:300], 'country':next((c for c in countries if c.upper() in ('US','USA','UNITED STATES')), ''),
                'workplace':'remote' if str(job.get('jobLocationType','')).upper() == 'TELECOMMUTE' else 'unknown'}
    for tag in soup(['script','style','nav','footer','header','noscript']):
        tag.decompose()
    main = soup.find('main') or soup.find('article') or soup
    return {'title':soup.title.get_text(strip=True)[:250] if soup.title else 'Target opportunity', 'company':'', 'description':main.get_text('\n',strip=True)[:100000], 'published_at':None, 'valid_through':None}
