"""Explicit model-backed drafts, verified against confirmed source content before review."""
import copy
import hashlib
import json
import re
from . import ai, ai_settings, db, resume_builder, job_parser, guidance, task_progress
from .models import OptimizationOutput, DraftAudit
from .network import ServiceError

def fingerprint(snapshot,ids=None):
    rows=[{'title':e['title'],'details':e['details'],'relationship_context':e.get('relationship_context',[]),'bullets':e.get('source_original_bullets',[i['original'] for i in e['content_items']])} for s in snapshot['sections'] for e in s['entries'] if ids is None or e['source_id'] in ids]
    if snapshot.get('linked_project_placements'):rows.append({'linked_project_placements':snapshot['linked_project_placements']})
    return hashlib.sha256(json.dumps(sorted(rows,key=lambda e:json.dumps(e,sort_keys=True)),sort_keys=True).encode()).hexdigest()

def estimate(snapshot,mode,profile):
    option=ai_settings.resolve(profile,mode)
    count=max(1000,(len(json.dumps(snapshot))+3)//4)
    stages=[ai_settings.estimate(option['model'],option['reasoning_effort'],count+extra,out,service_tier=option['service_tier'],max_output_tokens=profile.get('ai_max_output_tokens') or None) for extra,out in ((2000,2200),(3500,4500),(5000,4500),(6500,3000),(7000,1500))]
    return {**option,'usd':round(sum(v['usd'] for v in stages),6) if all(v['usd'] is not None for v in stages) else None,'input_tokens':sum(v['input_tokens'] for v in stages),'answer_tokens':15700,'assumed_reasoning_tokens':sum(v['assumed_reasoning_tokens'] for v in stages),'pricing_date':stages[0]['pricing_date'],'note':'Planning estimate for evidence strategy, drafting, editorial review, one optional measured layout correction and final auditing (at most five model requests). No automatic paid retries.'}


def apply(snapshot,draft,overrides=None):
    from . import resume_strategy
    result=resume_strategy.install(snapshot,draft.get('composed_items',{}));overrides=overrides or {}
    choices={r['record_id']:r for r in draft['entries']}
    omissions={r['record_id']:r['reason'] for r in draft.get('omissions',[])}
    known={v['item_id'] for s in result['sections'] for e in s['entries'] for v in e['content_items']}
    if any(k not in known or not isinstance(v,str) or not v.strip() or len(v)>1800 for k,v in overrides.items()):raise ServiceError('A draft edit is empty, too long, or no longer refers to available content.')
    order={choice['record_id']:n for n,choice in enumerate(draft['entries'])}
    for section in result['sections']:
        for entry in section['entries']:
            choice=choices.get(entry['source_id'],{});items={i['item_id']:i for i in choice.get('items',[])}
            if choices:entry['resume_order']=order.get(entry['source_id'],len(order))
            item_order={item['item_id']:n for n,item in enumerate(choice.get('items',[]))}
            entry['selection_reason']=choice.get('reason',omissions.get(entry['source_id'],'Not recommended for this role. Available for manual selection.'))
            entry['priority']=max([i['priority'] for i in items.values()] or [0])
            for index,item in enumerate(entry['content_items']):
                proposed=items.get(item['item_id'],{})
                # A later accepted Suggested edit takes precedence over an earlier AI rewrite.
                base=draft.get('baseline',{}).get(item['item_id'],item['original'])
                text=proposed.get('text',item['text']) if item['text']==base else item['text']
                if choices:item['resume_order']=item_order.get(item['item_id'],len(item_order))
                item.update({'text':overrides.get(item['item_id'],text),'priority':proposed.get('priority',0),'reason':proposed.get('reason',entry['selection_reason'])})
                if item['item_id'] in overrides:item['user_locked']=True
                entry['bullets'][index]=item['text']
    result['headline']=draft['headline'] if result.get('use_professional_headline',True) else '';return result

def initial_selection(snapshot,draft):
    choices={r['record_id']:{i['item_id'] for i in r['items']} for r in draft['entries']}
    return {'experience_ids':list(choices),'content':{e['source_id']:[i for i,item in enumerate(e['content_items']) if item['item_id'] in choices.get(e['source_id'],set())] for s in snapshot['sections'] for e in s['entries'] if e['source_id'] in choices}}

def evidence_sources(snapshot):
    """Keep record ownership while accepting original and previously checked wording."""
    records={}
    for section in snapshot['sections']:
        for entry in section['entries']:
            header=[entry['title'],entry['details']]
            variants=[entry.get('source_original_bullets',[]),[i['original'] for i in entry['content_items']],entry['bullets']]
            records[entry['source_id']]=list(dict.fromkeys('\n'.join([*header,*items]) for items in variants))
    # Add origins after all entry variants so an empty standalone project cannot overwrite them.
    for section in snapshot['sections']:
        for entry in section['entries']:
            for item in entry['content_items']:
                ref=item.get('project_source')
                if ref:
                    value=ref['project_title']+'\n'+ref['original']
                    if value not in records.setdefault(ref['project_id'],[]):records[ref['project_id']].append(value)
    return records

def source_texts(value):
    return value if isinstance(value,(list,tuple)) else [value]

def validate(output,snapshot,records):
    entries={e['source_id']:e for s in snapshot['sections'] for e in s['entries']}
    seen=set()
    for omission in output.get('omissions',[]):
        if omission['record_id'] not in entries:raise ServiceError('An omission referred to an unavailable Profile record.')
    for choice in output['entries']:
        rid=choice['record_id']
        if rid not in entries or rid in seen:raise ServiceError('The AI draft used an unavailable or repeated Profile record.')
        seen.add(rid);entry=entries[rid];items={i['item_id']:i for i in entry['content_items']};seen_items=set()
        if not choice['items'] and entry['category']!='education':raise ServiceError('The AI draft left a record without descriptive content. Retry optimization.')
        for item in choice['items']:
            if item['item_id'] not in items or item['item_id'] in seen_items:raise ServiceError('An AI rewrite referred to an unavailable or repeated content item.')
            seen_items.add(item['item_id']);source=items[item['item_id']]
            original=source['original'] if source.get('source_refs') else source['text']
            number_source=original+'\n'+'\n'.join(r.get('dates','') for r in source.get('source_refs',[]))
            if ai.numeric_facts(item['text'])-ai.numeric_facts(number_source):raise ServiceError('An AI rewrite introduced a number absent from its source. The previous draft is intact.')
            if source['field'] in ('skill','certification','gpa','course','education_detail','honors','url','tools') and ai.normalized(item['text'])!=ai.normalized(original):raise ServiceError('The AI changed a skill, course, credential, or structured fact. Retry optimization.')
            if __import__('app.resume_strategy',fromlist=['limitation_removed']).limitation_removed(source['text'],item['text']):raise ServiceError('An AI rewrite removed a source limitation.')
        if entry['category']=='project' and not any(items[i['item_id']]['field'] in ('description','contribution','accomplishment') for i in choice['items']):raise ServiceError('A recommended project needs at least one descriptive item.')
    if not output['entries']:raise ServiceError('OpenAI returned an empty draft. Your current selection is intact.')
    def evidence(rows):
        for e in rows:
            if e['record_id'] not in records or not any(ai.valid_quote(e['quote'],text) for text in source_texts(records[e['record_id']])):raise ServiceError('An AI draft source could not be verified against confirmed Profile content.')
    evidence(output['headline_evidence'])
    if output['headline'] and not output['headline_evidence']:raise ServiceError('The tailored headline had no supporting Profile evidence.')
    public_text='\n'.join(text for value in records.values() for text in source_texts(value))
    if ai.numeric_facts(output['headline'])-ai.numeric_facts(public_text):raise ServiceError('The headline introduced an unsupported number.')
    seen_keywords=set();keywords=[]
    for keyword in output['keywords']:
        if not ai.valid_quote(keyword['job_quote'],snapshot['posting_snapshot']['description']) or not ai.valid_quote(keyword['term'],keyword['job_quote']):raise ServiceError('A keyword did not occur in its posting source.')
        evidence(keyword['evidence'])
        if keyword['term'].casefold() not in seen_keywords:keywords.append(keyword);seen_keywords.add(keyword['term'].casefold())
    output['keywords']=keywords
    return output

async def create(user,snapshot,analysis,mode,feedback=None,guided=False,current=None):
    from . import resume_strategy
    if current is None or (feedback or {}).get('refresh_linked_evidence'):
        return await resume_strategy.create(user,snapshot,analysis,mode,feedback,guided,current)
    snapshot=resume_strategy.restore(snapshot,current)
    from . import resume_conversation
    snapshot['_optimization_source_signature']=resume_strategy.signature(resume_conversation.source(user,{'job_id':snapshot['job_id'],'analysis_id':snapshot.get('analysis_id')}))
    return await refine(user,snapshot,analysis,mode,feedback,guided,current)

async def refine(user,snapshot,analysis,mode,feedback=None,guided=False,current=None):
    from . import personalization
    request_version=personalization.request_version(user)
    snapshot=copy.deepcopy(snapshot);writing_guidance=guidance.selected('resume');snapshot['writing_guidance']=writing_guidance
    rows=resume_builder.catalog(snapshot,analysis)
    records=evidence_sources(snapshot)
    fields={i['item_id']:i['field'] for s in snapshot['sections'] for e in s['entries'] for i in e['content_items']}
    accepted={i['item_id']:i['text'] for s in snapshot['sections'] for e in s['entries'] for i in e['content_items'] if i.get('user_locked')}
    payload={'writing_guidance':writing_guidance,'task':'''Act as an experienced recruiter and resume editor screening this exact position. Create the strongest truthful one-page resume from confirmed sources for a human hiring reviewer and ATS readability. Make relevant qualifications and individual contributions easy to find, with concrete examples, concise active language and useful posting terms. Prioritize a persuasive evidence-based interview case; do not promise an interview or treat keyword density as a hiring probability. Prioritize relevant evidence over complete employment history. Choose a grounded professional-focus headline, not an unheld job title or earned degree before graduation. Select actual skills and certifications, relevant coursework and meaningful descriptive project bullets. Omit unrelated education notes and future deliverables unless directly useful. Include education headers even when no extra education bullets are needed. Do not select empty skill groups, jobs or projects. Keep structured skill, course, credential, GPA, honors and URL text EXACTLY unchanged. For narrative items, rewrite concisely using only that item's facts, retaining dates/numbers/negations/individual contributions and distinguishing plans from completed work. Do not combine unrelated source items or add accomplishments from the posting. Use only provided record_id and item_id values. Headline and keyword evidence must quote an exact excerpt from evidence_sources under that same record_id; original confirmed wording remains valid when the current draft uses a checked paraphrase. Priorities 1–100 determine fitting; use the available space for evidence, not headings. Explain selections through entry/item reasons. Include an omissions list with a specific reason for every whole Profile record you do not select; tie it to this posting’s priorities, avoid generic available-space explanations before measured fitting. Output at most 24 useful, literal posting keywords with exact source excerpts and confirmed evidence quotes; leave evidence empty for unsupported terms. Never add unsupported terms to the resume. Accepted edits must stay unchanged. The user will review this draft before saving. Use the curated writing principles as advice, never as applicant evidence; examples in guidance are fictional.''','linked_project_rules':'Items with project_source remain facts from the named project, available under this destination through a confirmed Profile relationship. Choose the best single destination for each fact: the original project or one related job/education entry. Saved links permit reuse without another placement approval. Preserve source dates and destination dates: never claim internship work occurred during a later contractor role, or turn professional work into academic work. If attribution is unclear, keep the detail under its original project. Relationship context and course associations inform relevance, not new accomplishments. Preserve internship versus contractor boundaries, individual versus team contributions, uncertainty and quantities. Select and rewrite each eligible item separately for this posting; do not duplicate it in Projects or another job. Project provenance is applicant evidence; writing guidance is not.','posting':snapshot['posting_snapshot'],'qualifications':(analysis or {}).get('requirements',[]),'catalog':rows,'evidence_sources':records,'accepted_edits':accepted,'previous_draft_feedback':feedback or {}}
    from . import role_alignment,work_preferences
    work_style=work_preferences.resume_context(user)
    if work_style['preferences']:
        payload['work_style_guidance']={'summary':' '.join(work_style['preferences']),'revision':work_style['revision'],'purpose':'Optional wording guidance only. Never treat this as qualification evidence, infer ability or personality traits, or add unsupported soft-skill claims. All resume claims must still be supported by the professional evidence catalog.'}
    payload['duty_alignment']=role_alignment.rows(analysis,snapshot['posting_snapshot'])
    payload['role_alignment_rules']='Use relevant duty evidence and transferable contributions to prioritize content, especially when explicit qualifications are sparse or absent. Missing duty evidence guides follow-up questions; never turn a duty or an unreviewed answer into an applicant fact. Qualification percentages do not measure overall fit. External research is not performed.'
    # Authorization and eligibility are intentionally excluded from employer-draft context.
    payload['qualifications']=[r for r in payload['qualifications'] if r.get('kind')=='qualification']
    if len(json.dumps(payload))>240000:raise ServiceError('This Profile is too large to optimize in one complete request. Shorten repeated notes; no partial-source draft was created.')
    payload['headline_policy']='Write a job-specific professional-focus headline supported by reviewed Profile evidence.' if snapshot.get('use_professional_headline',True) else 'Headlines are disabled: return an empty headline and no headline_evidence.'
    task_progress.stage('drafting')
    output,meta=await ai.structured(OptimizationOutput,payload,mode,retry_allowed=False)
    personalization.check_request(user,request_version)
    if 'prepared_headline' in (feedback or {}):output['headline']=feedback['prepared_headline']
    if current:output=constrain(output,snapshot,current,feedback or {})
    if snapshot.get('automatic_linked_evidence'):
        selected=initial_selection(snapshot,output)
        unique=resume_builder.select(apply(snapshot,output),selected['content'],selected['experience_ids'])
        kept={e['source_id']:{i['item_id'] for i in e['content_items']} for s in unique['sections'] for e in s['entries']}
        output['entries']=[{**e,'items':[i for i in e['items'] if i['item_id'] in kept[e['record_id']]]} for e in output['entries'] if e['record_id'] in kept]
    if not snapshot.get('use_professional_headline',True):output['headline']='';output['headline_evidence']=[]
    output['baseline']={i['item_id']:i['text'] for section in snapshot['sections'] for entry in section['entries'] for i in entry['content_items']}
    validate(output,snapshot,records)
    for choice in output['entries']:
        for item in choice['items']:
            layout_edit=(feedback or {}).get('fit_one_page') and fields[item['item_id']] in ('description','contribution','accomplishment')
            if item['item_id'] in accepted and item['item_id'] not in (feedback or {}).get('target_item_ids',[]) and not layout_edit and item['text']!=accepted[item['item_id']]:raise ServiceError('The model changed an edit you already accepted. Your draft remains intact; retry optimization.')
    layout_meta=None;rendered=None;fitted=None
    if guided:
        from . import resume_layout
        selected=initial_selection(snapshot,output)
        proposal=apply(snapshot,output)
        proposal['schema_version']=4
        selected_items={v['item_id'] for r in output['entries'] for v in r['items']}
        protected={i['item_id'] for s in proposal['sections'] for e in s['entries'] for i in e['content_items'] if i['field']=='certification' and i['item_id'] in selected_items}
        if current:
            fitted={**selected,'omitted':[]}
        else:
            task_progress.stage('fitting')
            fitted=await __import__('asyncio').to_thread(resume_layout.fit,proposal,resume_builder.catalog(proposal,analysis),selected,protected)
        selected_snapshot=resume_builder.select(proposal,fitted['content'],fitted['experience_ids'])
        task_progress.stage('rendering')
        rendered=await __import__('asyncio').to_thread(resume_layout.render,selected_snapshot)
        writable=set((feedback or {}).get('target_item_ids',[]))
        if (feedback or {}).get('fit_one_page'):writable.update(i['item_id'] for s in selected_snapshot['sections'] for e in s['entries'] for i in e['content_items'] if i['field'] in ('description','contribution','accomplishment'))
        target_ids={i['item_id'] for i in rendered['layout']['issues'] if i.get('item_id') and (i['item_id'] not in accepted or i['item_id'] in writable)}
        if rendered['layout']['pages']>1:
            target_ids.update(i['item_id'] for s in selected_snapshot['sections'] for e in s['entries'] for i in e['content_items'] if (i['item_id'] not in accepted or i['item_id'] in writable) and i['field'] in ('description','contribution','accomplishment'))
        if current and not (feedback or {}).get('fit_one_page'):
            previous={i['item_id']:i['text'] for s in current['sections'] for e in s['entries'] for i in e['content_items']}
            target_ids={i for i in target_ids if i not in previous or any(v['item_id']==i and v['text']!=previous[i] for s in selected_snapshot['sections'] for e in s['entries'] for v in e['content_items'])}
        if target_ids:
            task_progress.stage('layout')
            corrected,layout_meta=await ai.structured(OptimizationOutput,{'task':'Make one bounded layout correction: shorten ONLY the target narrative items to eliminate dangling words or overflow, retaining all facts, contributions and limitations. Use measured wrapped_items to remove redundant words and reduce line counts, prioritizing short carryover lines. When pages exceeds one, shorten enough wrapped bullets by at least one line each to bring the actual PDF to one page. Font sizes, spacing, margins and paper size are fixed and cannot be reduced. Preserve all other text, headline and selected content exactly, including every selected certification. Do not add or omit records/items. Return the complete draft schema.','target_item_ids':sorted(target_ids),'measured_layout':rendered['layout'],'proposal':output,'sources':rows},mode,retry_allowed=False)
            corrected=constrain(corrected,snapshot,selected_snapshot,{'target_item_ids':list(target_ids),'target_record_ids':[],'change_headline':False,'change_selection':False})
            validate(corrected,snapshot,records);corrected['baseline']=output['baseline'];output=corrected
            proposal=apply(snapshot,output);selected=initial_selection(snapshot,output)
            fitted={**selected,'omitted':fitted.get('omitted',[])}
            task_progress.stage('rendering')
            rendered=await __import__('asyncio').to_thread(resume_layout.render,resume_builder.select(proposal,selected['content'],selected['experience_ids']))
        if rendered['layout']['pages']>1 and (feedback or {}).get('change_selection'):
            task_progress.stage('fitting')
            fitted=await __import__('asyncio').to_thread(resume_layout.fit,proposal,resume_builder.catalog(proposal,analysis),initial_selection(snapshot,output),protected)
            task_progress.stage('rendering')
            rendered=await __import__('asyncio').to_thread(resume_layout.render,resume_builder.select(proposal,fitted['content'],fitted['experience_ids']))
        if rendered['layout']['pages']!=1:
            raise ServiceError('The revised PDF still exceeds one page after shortening. Your previous draft is intact; formatting and certifications were preserved. Request further wording cuts, or choose lower-priority content to omit.')
    task_progress.stage('checking')
    audit,audit_meta=await ai.structured(DraftAudit,{'task':'Check EVERY claim in the proposed headline and narrative rewrites against its specific source item. Reject invented tools, skills, credentials, accomplishments, employers, dates, quantities, impact, seniority or employment status; removed material limitations; team contributions presented as individual achievements; and future work presented as completed. Plausible is not supported. confirmed_sources includes record header facts such as attendance dates and expected graduation; header facts need not occur in bullet items. Distinguish expected graduation from a completed degree. For headline and keyword citations, evidence_sources contains original confirmed wording and previously checked wording, each owned by its record_id. Never use an unrelated record to support a citation. A previously checked composed item may combine its source_refs from the same original experience; retain those provenance and attribution limits. Evaluate whether keyword evidence actually supports using the term, not merely mentioning a course planned for later. Accept concise paraphrases when meaning is preserved. approved=true only if all claims and nonempty keyword evidence are supported. Return short issues; do not rewrite. Posting requirements are never applicant evidence.','linked_project_rules':'Check project_source on each item. Its project is the original source, and destination_id identifies the related record that may use it. Reject rewrites that broaden role attribution, erase uncertainty or contribution boundaries, or duplicate evidence.','confirmed_sources':rows,'evidence_sources':records,'proposal':output,'final_resume':__import__('app.resume_strategy',fromlist=['rendered_without_artifacts']).rendered_without_artifacts(rendered) if rendered else None,'user_constraints':(feedback or {}).get('user_constraints',{})},mode,retry_allowed=False)
    if not audit['approved'] or audit['issues']:raise ServiceError('The source check could not approve this draft. '+ ' '.join(audit['issues'][:3])+' Your previous draft and Profile are intact.')
    output.update({'writing_guidance':writing_guidance,'baseline':{i['item_id']:i['text'] for s in snapshot['sections'] for e in s['entries'] for i in e['content_items']},'source_fingerprint':fingerprint(snapshot),'job_id':snapshot.get('job_id'),'analysis_id':snapshot.get('analysis_id'),'schema_version':1,'posting_hash':job_parser.posting_hash(snapshot['posting_snapshot']),'ai':meta,'audit_ai':audit_meta,'source_checked':True})
    output['layout_ai']=layout_meta
    if current and current.get('optimization',{}).get('strategy') and rendered:
        from . import resume_strategy
        prior=current['optimization']['strategy']
        output['strategy']={**copy.deepcopy(prior),'priorities':resume_strategy.coverage(prior,rendered)}
    output['composed_items']={e['source_id']:copy.deepcopy([i for i in e['content_items'] if i.get('source_refs')]) for s in snapshot['sections'] for e in s['entries'] if any(i.get('source_refs') for i in e['content_items'])}
    output['user_constraints']=copy.deepcopy((feedback or {}).get('user_constraints',{}))
    if (feedback or {}).get('change_headline'):output['user_constraints']['headline']=output['headline']
    costs=[m for m in (meta,audit_meta,layout_meta) if m]
    output['actual_cost_usd']=round(sum(m['estimated_token_cost_usd'] or 0 for m in costs),6) if all(m['estimated_token_cost_usd'] is not None for m in costs) else None
    proposal=apply(snapshot,output)
    if not guided:fitted=await __import__('asyncio').to_thread(resume_builder.fit,proposal,resume_builder.catalog(proposal,analysis),initial_selection(proposal,output))
    reasons={r['record_id']:r['reason'] for r in output.get('omissions',[])}
    for omitted in fitted['omitted']:
        omitted['reason']=reasons.get(omitted['record_id'],omitted['reason'])
    output.update(fitted);output['catalog']=resume_builder.catalog(proposal,analysis)
    if guided:output['rendered_snapshot']=rendered
    task_progress.stage('saving')
    if snapshot.get('_optimization_source_signature'):
        from . import resume_strategy,resume_conversation
        fresh=resume_conversation.source(user,{'job_id':snapshot['job_id'],'analysis_id':snapshot.get('analysis_id')})
        if resume_strategy.signature(fresh)!=snapshot['_optimization_source_signature'] or job_parser.posting_hash(fresh['posting_snapshot'])!=job_parser.posting_hash(snapshot['posting_snapshot']):raise ServiceError('Your evidence or posting changed during this revision. The previous PDF remains intact.')
    record=db.save(user,'resume_draft',output)
    return record


def constrain(output,sources,current,feedback):
    """Preserve untouched text and selection; model feedback cannot silently reset them."""
    import copy
    output=copy.deepcopy(output)
    available={e['source_id']:e for s in sources['sections'] for e in s['entries']}
    old={e['source_id']:e for s in current['sections'] for e in s['entries']}
    proposed={e['record_id']:e for e in output['entries']}
    targets=set(feedback.get('target_item_ids',[]));records=set(feedback.get('target_record_ids',[]))
    if feedback.get('fit_one_page'):targets.update(i['item_id'] for e in available.values() for i in e['content_items'] if i['field'] in ('description','contribution','accomplishment'))
    changed_records=set(feedback.get('approved_record_ids',[]))
    selected=set(old)
    if feedback.get('change_selection'):
        for rid in records:
            if rid in proposed:selected.add(rid)
            else:selected.discard(rid)
    selected.update(rid for rid in changed_records if rid in proposed)
    result=[]
    for rid in available:
        if rid not in selected:continue
        source_items={i['item_id']:i for i in available[rid]['content_items']}
        choice=proposed.get(rid,{'record_id':rid,'reason':'Kept from your current draft.','items':[]})
        new_items={i['item_id']:i for i in choice['items']}
        previous={i['item_id']:i for i in old.get(rid,{}).get('content_items',[])}
        ids=set(previous)&set(source_items)
        if rid in changed_records or (feedback.get('change_selection') and rid in records):ids=set(new_items)
        items=[]
        for item in available[rid]['content_items']:
            key=item['item_id']
            if key not in ids:continue
            prior=previous.get(key,item)
            candidate=new_items.get(key)
            if key in targets and candidate:items.append(candidate)
            elif key not in previous and candidate:items.append(candidate)
            else:items.append({'item_id':key,'text':prior['text'],'priority':max(1,prior.get('priority',80)),'reason':'Preserved from your reviewed working draft.'})
        if items or available[rid]['category']=='education':result.append({**choice,'items':items})
    output['entries']=result
    if not feedback.get('change_headline'):
        output['headline']=current.get('headline','')
        output['headline_evidence']=current.get('optimization',{}).get('headline_evidence',output['headline_evidence'])
    return output
