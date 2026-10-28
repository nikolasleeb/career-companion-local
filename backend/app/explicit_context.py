"""Explicit, revision-checked conversation context, never automatic Profile evidence."""
import hashlib
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import Field
from .models import StrictModel

class Reference(StrictModel):
    kind: Literal['occupation', 'offer']
    id: str = Field(min_length=1, max_length=64)
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def occupation_snapshot(code):
    from . import career_explorer as explorer
    value = explorer.occupation(code)
    data = {**explorer.summary(code), 'skills': value['skills'], 'metadata': explorer.META}
    data.pop('reason', None)
    data.pop('also', None)
    return data

def occupation_link(code):
    value = occupation_snapshot(code)
    return {'code': code, 'title': value['title'], 'dataset_version': value['dataset_version'], 'revision': digest(value)}

def occupation_reference(code):
    link = occupation_link(code)
    return {'kind': 'occupation', 'id': code, 'revision': link['revision']}

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
            data = occupation_snapshot(ref.id)
            revision = digest(data)
            label = data['title'] + ' · occupation being explored, not a qualification'
            url = data['onet_url']
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
        if source['kind'] != 'explicit_occupation':
            raise HTTPException(422, 'Offer details can be shared with Career Coach, not added to a learning plan.')
        text = source['text']
        for at in range(0, min(len(text), 10800), 1800):
            chunks.append({'chunk_id': source['source_id'] + ':' + str(at), 'kind': 'occupation',
                           'title': source['label'], 'url': source['url'], 'text': text[at:at+1800],
                           'catalog_version': source['snapshot']['dataset_version'],
                           'checked_at': None, 'stale': False})
    return chunks
