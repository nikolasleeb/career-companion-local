"""Check public releases without credentials, account data, or container access."""
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
import httpx
from pydantic import BaseModel, ConfigDict
from . import config

REPOSITORY = 'nikolasleeb/career-companion-local'
RELEASES_URL = f'https://github.com/{REPOSITORY}/releases'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
VERSION = re.compile(r'v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?\Z')
DAY = 86400
LOCK = threading.Lock()


class Check(BaseModel):
    model_config = ConfigDict(extra='forbid')
    force: bool = False


def installed():
    fallback = {'version': 'dev', 'revision': 'unknown', 'built_at': '', 'channel': 'custom', 'edition': 'localhost'}
    try:
        data = json.loads(Path(__file__).with_name('build-info.json').read_text())
        if not isinstance(data, dict) or not VERSION.fullmatch(str(data.get('version', ''))):
            return fallback
        return {**fallback, **{k: str(data[k]) for k in ('version', 'revision', 'built_at', 'channel') if k in data}}
    except (OSError, ValueError):
        return fallback


def number(value):
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError('Unsupported release version.')
    return tuple(int(n or 0) for n in match.groups())


def _cache():
    try:
        value = json.loads((config.DATA_DIR / 'update-check.json').read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(value):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.update-', dir=config.DATA_DIR)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
        os.replace(name, config.DATA_DIR / 'update-check.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def status():
    current, cache, now = installed(), _cache(), time.time()
    latest = cache.get('latest')
    state = 'not_checked'
    if current['channel'] != 'release':
        state = 'custom'
    elif latest:
        try:
            a, b = number(current['version']), number(latest['version'])
            state = 'update_available' if b > a else 'up_to_date' if b == a else 'ahead'
        except (ValueError, KeyError, TypeError):
            state = 'unknown'
    stale = now - cache.get('checked_at', 0) >= DAY
    if cache.get('error') and current['channel'] == 'release':
        state = 'unable_to_check'
    return {'installed': current, 'latest': latest, 'state': state,
            'checked_at': cache.get('checked_at'), 'attempted_at': cache.get('attempted_at'),
            'stale': stale, 'error': cache.get('error', ''),
            'needs_check': stale and now >= cache.get('retry_at', 0),
            'can_check': now >= cache.get('retry_at', 0), 'next_check_at': cache.get('retry_at', 0), 'releases_url': RELEASES_URL}


def _release(data):
    tag = data.get('tag_name', '')
    if data.get('draft') is not False or data.get('prerelease') is not False or not VERSION.fullmatch(tag):
        raise ValueError('No complete stable release was found.')
    version = tag.removeprefix('v')
    names = {asset.get('name') for asset in data.get('assets', []) if asset.get('state') == 'uploaded'}
    required = {'compose.localhost.yaml', 'SHA256SUMS'} | {f'career-companion-{version}-linux-{arch}.tar.gz' for arch in ('amd64', 'arm64')}
    if not required <= names:
        raise ValueError('Release images are not ready yet.')
    return {'version': version, 'published_at': str(data.get('published_at', '')),
            'url': f'{RELEASES_URL}/tag/{tag}'}


def check(*, force=False):
    with LOCK:
        cache, now = _cache(), time.time()
        if now < cache.get('retry_at', 0) or (not force and now - cache.get('checked_at', 0) < DAY):
            return status()
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Career-Companion-Local-Update-Check', 'X-GitHub-Api-Version': '2026-03-10'}
        if cache.get('etag'):
            headers['If-None-Match'] = cache['etag']
        cache.update(attempted_at=now, retry_at=now + 60)
        try:
            # Fixed HTTPS destination. Do not send cookies, authorization or user data.
            with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
                with client.stream('GET', API_URL, headers=headers) as response:
                    if response.status_code == 304 and cache.get('latest'):
                        cache.update(checked_at=now, error='')
                    else:
                        if response.status_code in (403, 429):
                            cache['retry_at'] = now + 3600
                            raise ValueError('GitHub is limiting update checks. Try again later.')
                        if response.status_code == 404:
                            raise ValueError('No published release is available yet.')
                        response.raise_for_status()
                        raw = bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 262144:
                                raise ValueError('GitHub returned an oversized update response.')
                        latest = _release(json.loads(raw))
                        cache.update(latest=latest, checked_at=now, error='', etag=response.headers.get('etag', ''))
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            cache['error'] = 'Unable to check GitHub right now. Your installed app and saved data are unchanged.'
            cache['retry_at'] = max(cache['retry_at'], now + 900)
        _save(cache)
        return status()
