"""Per-request source boundaries enforced by the provider's output schema.

A display destination is not the owner of every fact shown there. Linked project
facts retain their original owner, even when selected for a job or education entry.
"""
from typing import Annotated,Literal,Union
import re
from pydantic import Field,create_model
from .models import StrictModel,ComposedResumeItem,ResumeComposition
from .network import ServiceError

NARRATIVE={'description','contribution','accomplishment','education_note','skill_context'}

def choices(types):return types[0] if len(types)==1 else Union[tuple(types)]

def exact_ids(values,large):
    # Patterns preserve the same finite whitelist for unusually large Profiles,
    # without exceeding the provider's total enum-value limit.
    return Annotated[str,Field(pattern='^(?:'+'|'.join(re.escape(v) for v in values)+')$')] if large else Literal[tuple(values)]

def composition_schema(evidence):
    facts=[f for f in evidence['facts'] if f['field']!='header'];by_origin={}
    for f in facts:by_origin.setdefault(f['record_id'],[]).append(f)
    branches={}
    for n,(origin,owned) in enumerate(by_origin.items()):
        for narrative in (True,False):
            subset=[f for f in owned if (f['field'] in NARRATIVE)==narrative]
            targets=set(t for f in subset for t in f['allowed_destinations'])
            for target in sorted(targets):
                ids=tuple(f['id'] for f in subset if target in f['allowed_destinations'])
                key=(origin,narrative,ids)
                branches.setdefault(key,set()).add(target)
    # Definitions are reused where destinations have the same exact permissions.
    large=sum(len(key[2]) for key in branches)+len(evidence['records'])>900
    variants=[]
    for n,((origin,narrative,ids),targets) in enumerate(branches.items()):
        kind=create_model('SourceGroup'+str(n+1),__base__=ComposedResumeItem,
            source_ids=(list[exact_ids(ids,large)],Field(min_length=1,max_length=8 if narrative else 1)))
        variants.append((kind,targets))
    destinations=[]
    for n,record in enumerate(evidence['records']):
        rid=record['record_id'];allowed=[kind for kind,targets in variants if rid in targets]
        if not allowed and record['category']!='education':continue
        # Empty education headers are valid; no facts are invented to fill them.
        item_type=choices(allowed) if allowed else ComposedResumeItem
        kind=create_model('Destination'+str(n+1),__base__=StrictModel,
            record_id=(Literal[rid],...),reason=(str,...),
            items=(list[item_type],Field(min_length=0 if record['category']=='education' else 1,max_length=20 if allowed else 0)))
        destinations.append(kind)
    if not destinations:raise ServiceError('There is no reviewed evidence available for a resume.')
    return create_model('ResumeComposition',__base__=ResumeComposition,
        entries=(list[choices(destinations)],Field(min_length=1,max_length=40)))

def groups(evidence):
    records={r['record_id']:r for r in evidence['records']};result=[]
    for origin in dict.fromkeys(f['record_id'] for f in evidence['facts']):
        owned=[f for f in evidence['facts'] if f['record_id']==origin and f['field']!='header']
        if not owned:continue
        record=records[origin]
        result.append({'original_experience_id':origin,'title':record['title'],'category':record['category'],
            'narrative_source_ids':[f['id'] for f in owned if f['field'] in NARRATIVE],
            'separate_qualification_source_ids':[f['id'] for f in owned if f['field'] not in NARRATIVE],
            'rule':'Combine narrative sources only within this original experience. Select each qualification separately. Links permit display placement, not merging ownership.'})
    return result
