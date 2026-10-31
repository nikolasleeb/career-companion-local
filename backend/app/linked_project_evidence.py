"""Explicit, versioned placement of project source items; never writes Profile facts."""
import copy
import hashlib
import json
import re
from difflib import SequenceMatcher
from fastapi import HTTPException
from . import profile_answers, resume_data
from .network import ServiceError

NARRATIVE = {'description', 'contribution', 'accomplishment'}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def normalized(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))

def overlaps(left, right):
    a, b = normalized(left), normalized(right)
    if a == b:return True
    if min(len(a.split()), len(b.split())) < 7:return False
    return SequenceMatcher(None, a, b).ratio() >= .78

def candidates(user):
    records = {r['id']:r for r in profile_answers.records(user)}
    entries = {rid:resume_data.entry_snapshot(r['data'], rid, granular=True) for rid,r in records.items()}
    result = []
    for rid,record in records.items():
        data = record['data']
        if data['category'] != 'project':continue
        jobs = [entries[j] for j in data.get('linked_employment_ids', []) if j in entries and entries[j]['category'] == 'employment']
        if not jobs:continue
        for item in entries[rid]['content_items']:
            if item['field'] not in NARRATIVE:continue
            targets = []
            for job in jobs:
                conflicts = [{'item_id':i['item_id'], 'text':i['original']} for i in job['content_items'] if i['field'] in NARRATIVE and overlaps(item['original'], i['original'])]
                targets.append({'id':job['source_id'], 'title':job['title'], 'organization':job.get('organization',''), 'dates':job.get('dates',''), 'overlaps':conflicts, 'revision':records[job['source_id']]['updated_at']})
            ref = {'project_id':rid, 'item_id':item['item_id'], 'field':item['field'], 'original':item['original'], 'project_title':data['title'], 'project_revision':record['updated_at'], 'reviewed_answer_sources':copy.deepcopy([a for a in data.get('answer_sources', []) if normalized(item['original']) in normalized(a.get('text','')) or normalized(a.get('text','')) and normalized(a['text']) in normalized(item['original'])])}
            # Any source, reviewed answer, role boundary or relationship change requires a new review.
            stamp = digest({'source':ref, 'reviewed_answers':data.get('answer_sources',[]), 'relationships':data.get('relationship_context', []), 'targets':targets})
            result.append({**ref, 'source_fingerprint':stamp, 'jobs':targets})
    return result

def checked(user, choices):
    available = {(r['project_id'],r['item_id']):r for r in candidates(user)}
    seen = set();result = []
    for choice in choices:
        choice = choice.model_dump() if hasattr(choice, 'model_dump') else copy.deepcopy(choice)
        key = (choice['project_id'],choice['item_id'])
        if key in seen:raise HTTPException(400, 'Choose one destination for each project detail.')
        seen.add(key);row = available.get(key)
        if not row or row['source_fingerprint'] != choice['source_fingerprint']:
            raise HTTPException(409, 'Project evidence or its job links changed. Reopen Linked project evidence and review the current sources. Historical drafts remain available.')
        if choice['placement'] == 'employment':
            job = next((j for j in row['jobs'] if j['id'] == choice.get('employment_id')), None)
            if not job:raise HTTPException(400, 'Confirm a currently linked employment role for this project detail.')
            if job['overlaps'] and not choice.get('replace_overlaps'):
                raise HTTPException(409, 'Review overlapping job bullets before placing this project detail under the role.')
        elif choice.get('employment_id'):
            raise HTTPException(400, 'Only Work Experience placements can specify a role.')
        result.append((choice,row))
    return result

def entries(snapshot):
    return {e['source_id']:e for s in snapshot['sections'] for e in s['entries']}

def sync(entry):
    entry['bullets'] = [i['text'] for i in entry['content_items']]
    entry['source_original_bullets'] = [i['original'] for i in entry['content_items']]

def apply(snapshot, reviewed):
    """Move individual items into a single catalog location with their original provenance."""
    full = copy.deepcopy(snapshot);rows = entries(full)
    if full.pop('automatic_linked_evidence',None):
        for entry in rows.values():
            entry['content_items']=[i for i in entry['content_items'] if not i.get('project_source',{}).get('destination_id')]
            sync(entry)
    # Undo previous placements in this working source, retaining original item identities.
    previous={(c['project_id'],c['item_id']):c for c in full.get('linked_project_placements',[])}
    originals = full.pop('linked_project_originals', {})
    wording = {}
    for rid,entry in rows.items():
        for item in entry['content_items']:
            ref = item.get('project_source')
            wording[(ref['project_id'],ref['item_id']) if ref else (rid,item['item_id'])] = item['text']
    for rid,items in originals.items():
        if rid in rows:
            rows[rid]['content_items'] = copy.deepcopy(items)
            for item in rows[rid]['content_items']:
                item['text'] = wording.get((rid,item['item_id']), item['text'])
            sync(rows[rid])
    backups = {}
    def remember(rid):
        if rid not in backups:backups[rid] = copy.deepcopy(rows[rid]['content_items'])
    for choice,row in reviewed:
        pid = row['project_id'];project = rows.get(pid)
        if not project:raise HTTPException(409, 'The source project is unavailable in this draft. Build a fresh draft before placing its evidence.')
        remember(pid)
        # An explicit review can refresh this specific item, without refreshing unrelated facts.
        project['content_items'] = [i for i in project['content_items'] if i['item_id'] != row['item_id']]
        item = {'item_id':row['item_id'], 'field':row['field'], 'original':row['original'], 'text':wording.get((pid,row['item_id']),row['original']) if previous.get((pid,row['item_id']),{}).get('source_fingerprint')==row['source_fingerprint'] else row['original']}
        if choice['placement'] == 'project':project['content_items'].append(item)
        if choice['placement'] == 'employment':
            jid = choice['employment_id'];job = rows.get(jid)
            if not job or job['category'] != 'employment':raise HTTPException(409, 'The destination job is unavailable in this draft. Build a fresh draft before placing its evidence.')
            remember(jid);target = next(j for j in row['jobs'] if j['id'] == jid)
            if (job['title'],job.get('organization',''),job.get('dates','')) != (target['title'],target['organization'],target['dates']):
                raise HTTPException(409, 'The destination job changed since this draft. Build a fresh draft, then review the project placement for that role.')
            conflicts = {i['item_id'] for i in target['overlaps']}
            # Removal is explicit: the review names every overlapping bullet being replaced.
            job['content_items'] = [i for i in job['content_items'] if i['item_id'] not in conflicts]
            ref = {k:copy.deepcopy(v) for k,v in row.items() if k != 'jobs'}
            ref.update({'employment_id':jid, 'employment_title':job['title']})
            item.update({'item_id':digest([pid,row['item_id']])[:24], 'project_source':ref})
            job['content_items'].append(item)
    for entry in rows.values():sync(entry)
    full['linked_project_placements'] = [copy.deepcopy(c) for c,r in reviewed]
    full['linked_project_originals'] = backups
    return full

def validate_selected(snapshot):
    """Final deterministic duplicate gate, also used after fitting and manual editing."""
    seen = set();narrative = []
    for rid,entry in entries(snapshot).items():
        for item in entry.get('content_items', []):
            ref = item.get('project_source');key = (ref['project_id'],ref['item_id']) if ref else (rid,item['item_id'])
            if key in seen:raise ServiceError('The same project source item cannot appear in more than one resume location.')
            seen.add(key)
            if item['field'] in NARRATIVE:narrative.append((ref,normalized(item['text'])))
    for n,(ref,text) in enumerate(narrative):
        if any(text == other and (ref or other_ref) for other_ref,other in narrative[:n]):
            raise ServiceError('A linked project bullet duplicates selected content. Omit the overlapping bullet before updating the draft.')


def automatic(snapshot):
    """Offer confirmed project facts through saved relationships; never mutate Profile."""
    full=copy.deepcopy(snapshot);rows=entries(full)
    for pid,project in list(rows.items()):
        if project['category']!='project':continue
        links=[]
        for relation in project.get('relationship_context',[]):
            target=relation.get('record_id') or relation.get('id') or relation.get('education_id')
            if target in rows:links.append(target)
        # Original metadata uses these identifiers; relationship_context supplies readable context.
        links+=project.get('linked_employment_ids',[])+project.get('linked_education_ids',[])
        links += [r['education_id'] for r in project.get('linked_courses',[])]
        for target_id in dict.fromkeys(links):
            target=rows.get(target_id)
            if not target or target['category'] not in ('employment','education','coursework'):continue
            for item in project['content_items']:
                if item['field'] not in NARRATIVE:continue
                ref={'project_id':pid,'item_id':item['item_id'],'original':item['original'],
                     'project_title':project['title'],'project_dates':project.get('dates',''),
                     'destination_id':target_id,'employment_id':target_id if target['category']=='employment' else '',
                     'destination_category':target['category'],'destination_title':target['title'],
                     'reviewed_answer_sources':copy.deepcopy([a for a in project.get('reviewed_answer_sources',[]) if normalized(a.get('text','')) and (normalized(a['text']) in normalized(item['original']) or normalized(item['original']) in normalized(a['text']))])}
                target['content_items'].append({**copy.deepcopy(item),'item_id':digest([pid,item['item_id'],target_id])[:24], 'project_source':ref})
            sync(target)
    full['automatic_linked_evidence']=1
    return full


def deduplicate(snapshot):
    """One source item/location; prefer selected higher-priority facts. No added facts."""
    if not snapshot.get('automatic_linked_evidence'):return snapshot
    candidates=[]
    for rid,entry in entries(snapshot).items():
        for index,item in enumerate(entry.get('content_items',[])):
            ref=item.get('project_source')
            origin=(ref['project_id'],ref['item_id']) if ref else (rid,item['item_id'])
            candidates.append((-(item.get('priority',0)),bool(ref),rid,index,origin,item))
    kept=set();origins=set();narratives=[]
    for _,linked,rid,index,origin,item in sorted(candidates,key=lambda v:v[:4]):
        if origin in origins:continue
        if item['field'] in NARRATIVE and any((linked or prior_linked) and equivalent(item['original'],text) for prior_linked,text in narratives):continue
        origins.add(origin);kept.add((rid,index))
        if item['field'] in NARRATIVE:narratives.append((linked,item['original']))
    for rid,entry in entries(snapshot).items():
        entry['content_items']=[i for n,i in enumerate(entry['content_items']) if (rid,n) in kept];sync(entry)
    for section in snapshot['sections']:
        section['entries']=[e for e in section['entries'] if e['content_items'] or e['category']=='education']
    return snapshot


def equivalent(left,right):
    # Similar wording with different quantities or limitations is not a duplicate fact.
    import re
    numbers=lambda text:set(re.findall(r'\d+(?:[.,]\d+)*',text))
    limits=lambda text:set(re.findall(r'\b(no|not|never|without|incomplete|approximately|planned|expected)\b',text.lower()))
    return numbers(left)==numbers(right) and limits(left)==limits(right) and overlaps(left,right)
