"""Explicit, revision-checked conversation context, never automatic Profile evidence."""
import hashlib
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import Field
from .models import StrictModel

class Reference(StrictModel):
    kind: Literal['occupation', 'offer', 'readiness']
    id: str = Field(min_length=1, max_length=64)
    salary_area: str | None = Field(default=None,max_length=40)
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def occupation_snapshot(code,salary_area=None):
    from . import career_explorer as explorer
    value = explorer.occupation(code)
    data = {**explorer.summary(code,salary_area=salary_area or 'US'), 'skills': value['skills'], 'metadata': explorer.META}
    data.pop('reason', None)
    data.pop('also', None)
    if salary_area is not None:data['salary_area']=salary_area
    return data

def occupation_link(code,salary_area=None):
    value = occupation_snapshot(code,salary_area)
    return {'code': code, 'title': value['title'], 'dataset_version': value['dataset_version'], 'revision': digest(value),**({'salary_area':salary_area} if salary_area is not None else {})}

def occupation_reference(code,salary_area=None):
    link = occupation_link(code,salary_area)
    return {'kind': 'occupation', 'id': code, 'revision': link['revision'],**({'salary_area':salary_area} if salary_area is not None else {})}

def resolve(user, references):
    sources = []
    seen = set()
    for raw in references:
        ref = Reference.model_validate(raw)
        key = (ref.kind, ref.id)
        if key in seen:
            continue
        seen.add(key)
        if ref.kind == 'occupation':
            data = occupation_snapshot(ref.id,ref.salary_area)
            revision = digest(data)
            label = data['title'] + ' · occupation being explored, not a qualification'
            url = data['onet_url']
        elif ref.kind == 'readiness':
            from . import readiness, coach_access
            report = readiness.owned(user, ref.id, 'readiness_report')
            if not coach_access.source_allowed(user, report['data'].get('source_snapshot',[])):
                raise HTTPException(409, 'Readiness sharing changed. Reassess before sharing this report.')
            data = {'session_id': report['data']['session_id'], 'report_id': ref.id, 'reply': report['data']['reply'], 'label': 'Generated career guidance, not applicant evidence', 'source_snapshot': [{k:s[k] for k in ('record_id','kind','revision') if k in s} for s in report['data']['source_snapshot']]}
            revision = readiness.digest(report['data'])
            label = data['label']
            url = ''
        else:
            from . import application_offers
            data = application_offers.shared_snapshot(user, ref.id)
            revision = digest(data)
            label = data['label'] + ' · explicitly shared offer details'
            url = ''
        if ref.revision != revision:
            raise HTTPException(409, 'Selected context changed. Refresh its preview and review it again. Your draft is preserved; no new AI request was sent.')
        sources.append({'source_id': 'explicit:' + ref.kind + ':' + ref.id, 'record_id': ref.id,
                        'kind': 'explicit_' + ref.kind, 'label': label, 'revision': revision,
                        'url': url, 'text': json.dumps(data, ensure_ascii=False), 'snapshot': data})
    return sources

def plan_chunks(sources):
    chunks = []
    for source in sources:
        if source['kind'] == 'explicit_readiness':
            chunks.append({'chunk_id': 'readiness:'+source['record_id'], 'kind':'readiness', 'title':source['label'], 'url':'', 'text':json.dumps(source['snapshot']['reply'],ensure_ascii=False)[:10800], 'catalog_version':source['revision'], 'checked_at':None, 'stale':False})
            continue
        if source['kind'] != 'explicit_occupation':
            raise HTTPException(422, 'Offer details can be shared with Career Coach, not added to a learning plan.')
        text = source['text']
        for at in range(0, min(len(text), 10800), 1800):
            chunks.append({'chunk_id': source['source_id'] + ':' + str(at), 'kind': 'occupation',
                           'title': source['label'], 'url': source['url'], 'text': text[at:at+1800],
                           'catalog_version': source['snapshot']['dataset_version'],
                           'checked_at': None, 'stale': False})
    return chunks
