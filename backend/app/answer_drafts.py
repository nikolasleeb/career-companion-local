"""Shared manual review for project evidence and reflection stories, reusing Profile answer protections."""
import copy
import json
import re
from fastapi import HTTPException
from . import db, profile_answers as library
from .models import ExperienceItem
from .resume_conversation import write

def owned(user,id):
    result=db.get(user,id,'answer_draft')
    if not result:raise HTTPException(404,'Answer draft not found.')
    return result

def save(user,id,body):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        record=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='answer_draft'",(id,user)).fetchone()) if id else None
        if id and not record:raise HTTPException(404,'Answer draft not found.')
        old=record['data'] if record else {'version':0,'status':'draft','builder':'work_style','questions':[{'id':'story','text':body.question or 'Describe a real professional example.'}],'findings':[],'history':[]}
        if old['version']!=body.expected_version:raise HTTPException(409,'This answer changed. Reload before saving.')
        if old['status']!='draft':raise HTTPException(409,'This answer was already reviewed. Edit the reviewed answer in Profile.')
        if any(len(value)>2000 for value in body.question_answers.values()) or set(body.question_answers)-{q['id'] for q in old.get('questions',[])}:raise HTTPException(400,'Answer only this draft’s questions, with up to 2,000 characters each.')
        if body.experience_id:library.owned_experience(c,user,body.experience_id)
        links=library.validate_links(c,user,body.experience_ids) if body.experience_ids is not None else [body.experience_id] if body.experience_id else []
        old['experience_ids']=links
        old.update(version=old['version']+1,title=body.title,text=body.text,contribution=body.contribution,experience_id=body.experience_id,question_answers=body.question_answers)
        if not record:
            if body.prompt_id:
                prompt=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='story_prompts'",(body.prompt_id,user)).fetchone())
                if not prompt or body.question not in prompt['data']['questions']:raise HTTPException(400,'Choose a prompt belonging to this account.')
                old['prompt_id']=body.prompt_id;old['job_id']=prompt['data'].get('job_id','')
            elif body.question:
                from .work_style import DIMENSIONS
                if body.question not in [d['prompt'] for d in DIMENSIONS]:raise HTTPException(400,'Choose a bundled reflection prompt.')
        id=write(c,user,'answer_draft',old,id)
    return owned(user,id)

def review(user,id,body):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        record=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='answer_draft'",(id,user)).fetchone())
        if not record:raise HTTPException(404,'Answer draft not found.')
        data=record['data']
        # Retry-safe approval: repeat the same decision rather than creating another record.
        if data['status']!='draft':
            if data.get('review_request')==body.model_dump():return library.row(c,user,data['profile_answer_id']) if data.get('profile_answer_id') else record
            raise HTTPException(409,'This draft was already reviewed. Edit its current Profile answer instead.')
        if body.expected_version!=data['version']:raise HTTPException(409,'This answer changed. Review the latest version.')
        if body.rejected:
            data.update(status='rejected',version=data['version']+1,review_request=body.model_dump(),reviewed_at=db.now());write(c,user,'answer_draft',data,id);return {**record,'data':data}
        if not body.confirmed or not body.text.strip() or not body.title.strip():raise HTTPException(400,'Review and confirm nonempty professional details.')
        if re.search(library.PRIVATE,body.text+' '+body.contribution,re.I):raise HTTPException(400,'Authorization belongs in private Profile settings.')
        if data['builder']=='project' and not body.contribution.strip():raise HTTPException(400,'Confirm what you personally contributed; project contents alone do not establish your work.')
        target=library.owned_experience(c,user,body.experience_id) if body.experience_id else None
        if target and (not target['data'].get('confirmed') or target['updated_at']!=body.experience_updated_at):raise HTTPException(409,'The selected Profile experience changed. Reload before applying these details.')
        snapshot=None
        if data.get('snapshot_id'):
            snapshot=db.decode(c.execute("SELECT * FROM entities WHERE id=? AND user_id=? AND kind='project_snapshot'",(data['snapshot_id'],user)).fetchone())
            if not snapshot:raise HTTPException(409,'The source snapshot is unavailable.')
            files={f['file_path']:f['text'] for f in snapshot['data']['files']}
            if any(f['file_path'] not in files or f['quote'] not in files[f['file_path']] for f in data['findings']):raise HTTPException(409,'The source excerpts could not be validated.')
        text='\n'.join(filter(None,[body.text.strip(),body.contribution.strip()]))
        previous=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)) if (lambda a:a.get('status')=='confirmed' and a.get('answer_kind')=='experience' and library.norm(a.get('text'))==library.norm(text) and (not target or a.get('experience_id')==target['id']))(json.loads(r['payload']))),None)
        if previous and not target and previous['data'].get('experience_id'):
            target=library.owned_experience(c,user,previous['data']['experience_id'])
        rid=target['id'] if target else ''
        if body.create_experience and not target:
            rid=write(c,user,'experience',ExperienceItem(title=body.title,category='project',contribution=text,confirmed=True,project_url=snapshot['data'].get('url','') if snapshot else '',project_urls=(snapshot['data'].get('urls') or []) if snapshot else []).model_dump())
        elif body.update_experience and target:
            value=copy.deepcopy(target['data'])
            if library.norm(text) not in library.norm('\n'.join(str(v) for v in value.values())):value['contribution']='\n'.join(filter(None,[value.get('contribution',''),text]))
            write(c,user,'experience',ExperienceItem.model_validate(value).model_dump(),rid)
        links=library.validate_links(c,user,body.experience_ids if body.experience_ids is not None else [rid] if rid else [])
        if rid and rid not in links:links.insert(0,rid)
        library.require_links(links)
        source={'builder':data['builder'],'draft_id':id,'questions':data.get('questions',[]),'message':data.get('text',''),'question_answers':data.get('question_answers',{}),'contribution_confirmation':body.contribution,'reviewed_at':db.now(),'manual_review':True}
        for key in ('snapshot_id','analysis_id','prompt_id','job_id'):
            if data.get(key):source[key]=data[key]
        if snapshot:source.update(commit=snapshot['data'].get('commit',''),repositories=copy.deepcopy(snapshot['data'].get('members',[])),excerpts=copy.deepcopy(data['findings']))
        aid=library.key(user,'external:'+id)
        existing=next((db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind='profile_answer'",(user,)) if (lambda a:a.get('status')=='confirmed' and a.get('answer_kind')=='experience' and library.norm(a.get('text'))==library.norm(text) and a.get('experience_id','')==rid)(json.loads(r['payload']))),None)
        if existing:
            aid=existing['id'];existing['data']['sources'].append(source);library.write(c,user,existing['data'],aid)
        else:
            library.write(c,user,{'version':1,'status':'confirmed','answer_kind':'experience','title':body.title,'text':text,'experience_id':links[0],'experience_ids':links,'category':'project','record_context':{},'backed_fields':{'contribution':text} if body.create_experience or body.update_experience else {},'scope':{},'sources':[source],'history':[],'review_history':[{'reviewed_at':db.now(),'text':text}]},aid)
        data.update(status='reviewed',version=data['version']+1,profile_answer_id=aid,review_request=body.model_dump(),reviewed_at=db.now())
        write(c,user,'answer_draft',data,id);library.touch_resumes(c,user,None,rid or aid)
    return db.get(user,aid,'profile_answer')
