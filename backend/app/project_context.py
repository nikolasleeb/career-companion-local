"""Saved project observations for questions, never confirmed applicant facts."""
import copy
import json
from fastapi import HTTPException
from . import db
from .network import ServiceError

NOTICE='Project materials describe artifacts, not confirmed personal contributions. Use only to ask posting-specific questions; reuse already reviewed answers first.'

def answered_questions(user):
    from .profile_answers import confirmed,norm,experience_ids
    answered=set()
    for row in confirmed(user):
        if row['data']['answer_kind']!='experience':continue
        for source in row['data'].get('sources',[]):
            keys={r.get('experience_id') or r['snapshot_id'] for r in source.get('project_refs',[])}
            if not keys:keys=set(experience_ids(row['data']))
            for q in source.get('questions',[]):answered.update((norm(q['text']),key) for key in keys)
    return answered

def fresh_questions(user,questions):
    from .profile_answers import norm
    answered=answered_questions(user)
    def needed(q):
        keys={r.get('experience_id') or r['snapshot_id'] for r in q.get('project_refs',[])}
        return not keys or not all((norm(q['text']),key) in answered for key in keys)
    return [q for q in questions if needed(q)]

def catalog(user,data):
    from .project_sources import passages
    from .models import project_links
    projects={r['id']:r for r in db.list_entities(user,'experience') if r['data'].get('confirmed') and r['data'].get('category')=='project'}
    snapshots={r['id']:r for r in db.list_entities(user,'project_snapshot') if not r['data'].get('archived')}
    analyses={}
    for row in db.list_entities(user,'project_analysis'):
        analyses.setdefault(row['data']['snapshot_id'],row)
    explicit=set(data.get('project_snapshot_ids',[])[:5]);results=[];seen=set()
    ordered=sorted(snapshots.values(),key=lambda s:(analyses.get(s['id']) or {}).get('created_at',''),reverse=True)
    for snap in ordered:
        sid=snap['id'];value=snap['data'];rid=value.get('experience_id','');project=projects.get(rid);analysis=analyses.get(sid)
        if sid not in explicit:
            if not project or not analysis or rid in seen:continue
            links=sorted(v.rstrip('/') for v in project_links(project['data']))
            saved=sorted(v.rstrip('/') for v in value.get('urls') or [value.get('url','')])
            if value.get('provider')=='github' and links and links!=saved:continue
            seen.add(rid)
        files={f['file_path']:f['text'] for f in value['files']}
        findings=[copy.deepcopy(f) for f in (analysis or {}).get('data',{}).get('findings',[]) if f.get('file_path') in files and f.get('quote') and f['quote'] in files[f['file_path']]]
        results.append({'context_id':analysis['id'] if analysis else sid,'experience_id':rid if project else '',
            'project_title':project['data']['title'] if project else value['label'],'snapshot_id':sid,'analysis_id':analysis['id'] if analysis else '',
            'label':value['label'],'summary':(analysis or {}).get('data',{}).get('summary',''),'findings':findings,
            'commit':value.get('commit',''),'repositories':copy.deepcopy(value.get('members',[])),
            'files':passages(value)[:3] if sid in explicit else [],'notice':NOTICE})
    if len(json.dumps(results))>180000:raise ServiceError('Saved project context is too large for one complete question review. Archive outdated project materials before continuing; no AI request was started.')
    return results

def references(ids,context):
    rows={r['context_id']:r for r in context}
    if len(ids)!=len(set(ids)) or set(ids)-rows.keys():raise ServiceError('A project question referred to unavailable saved materials. No project facts were approved.')
    return [{k:copy.deepcopy(v) for k,v in rows[id].items() if k not in ('files','notice','context_id','summary')} for id in ids]

def attach_assessments(output,context):
    result=copy.deepcopy(output)
    for field in ('requirements','duty_assessments'):
        for row in result.get(field,[]):
            refs=references(row.pop('project_context_ids',[]),context)
            if refs and row['kind']=='eligibility':raise ServiceError('Private eligibility questions cannot use project materials.')
            row['project_refs']=refs if row.get('question','').strip() else []
    return result

def question_refs(data,proposal,builder):
    from .profile_answers import proposal_questions
    rows=[]
    for q in proposal_questions(data,proposal,builder):
        for ref in q.get('project_refs',[]):
            if ref not in rows:rows.append(copy.deepcopy(ref))
    return rows

def bind_proposal(user,data,proposal,builder):
    """The server associates submitted answers with projects; the model cannot approve facts."""
    if proposal.get('category')=='authorization' or proposal.get('kind')=='motivation':return
    refs=question_refs(data,proposal,builder)
    key='record_id' if builder=='resume' else 'profile_record_id'
    target=db.get(user,proposal.get(key,''),'experience')
    if not refs and target and target['data'].get('category')=='project':
        context=catalog(user,data)
        refs=references([r['context_id'] for r in context if r['experience_id']==target['id']],context)
    if not refs and not (target and target['data'].get('category')=='project'):return
    candidates=list(dict.fromkeys(r['experience_id'] for r in refs if r.get('experience_id')))
    selected=candidates[0] if len(candidates)==1 else target['id'] if not candidates and target else ''
    proposal.update(project_refs=refs,evidence_only=True,evidence_experience_id=selected,allow_standalone=not candidates and not target)

def destination(c,user,proposal,selected='',expected='',keep_standalone=False):
    if keep_standalone:
        if not proposal.get('allow_standalone'):raise HTTPException(400,'Choose the project this answer describes.')
        return None
    rid=selected or proposal.get('evidence_experience_id','')
    record=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='experience'",(rid,user)).fetchone()) if rid else None
    if not record or not record['data'].get('confirmed') or record['data'].get('category')!='project':raise HTTPException(400,'Choose the confirmed Profile project for these reviewed details.')
    original_id=proposal.get('record_id') or proposal.get('profile_record_id')
    stamp=expected
    if not stamp and rid==original_id:stamp=proposal.get('expected_updated_at') or proposal.get('profile_expected_updated_at')
    if stamp and stamp!=record['updated_at']:raise HTTPException(409,'This Profile project changed. Reload and review the current project before linking these details.')
    return record

def provenance(refs):
    return {'project_refs':copy.deepcopy(refs)} if refs else {}
