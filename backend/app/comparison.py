"""Posting-owned classifications and reproducible, source-linked qualification scores."""
import re
import hashlib
from .network import ServiceError
from . import job_parser
from .posting_extraction import source_quote_valid

PRIVATE_FIELDS=('us_citizen','authorized_us','sponsorship_now','sponsorship_future')
EDITABLE_FIELDS=('description','contribution','accomplishments','honors','relevant_courses')

def score(requirements):
    groups={};contributions=[]
    for importance in ('required','preferred'):
        rows=[r for r in requirements if r.get('kind')=='qualification' and r.get('importance')==importance]
        earned=sum({'supported':1,'partial':.5}.get(r['status'],0) for r in rows)
        groups[importance]={'total':len(rows),'supported':sum(r['status']=='supported' for r in rows),'partial':sum(r['status']=='partial' for r in rows),'unresolved':sum(r['status']=='unknown' for r in rows),'not_met':sum(r['status']=='not_met' for r in rows),'earned':earned}
    weights={'required':.7,'preferred':.3}
    active=[k for k,v in groups.items() if v['total']];denominator=sum(weights[k] for k in active)
    for r in requirements:
        k=r.get('importance')
        if r.get('kind')=='qualification' and k in active:
            maximum=100*weights[k]/denominator/groups[k]['total']
            contributions.append({'criterion_id':r.get('criterion_id',''),'title':r['keyword'],'group':k,'status':r['status'],'earned':round(maximum*{'supported':1,'partial':.5}.get(r['status'],0),2),'maximum':round(maximum,2)})
    value=int(100*sum(weights[k]*groups[k]['earned']/groups[k]['total'] for k in active)/denominator+.5) if active else None
    total=sum(groups[k]['total'] for k in active)
    covered=sum(groups[k]['supported']+groups[k]['partial'] for k in active)
    return {'value':value,'groups':groups,'contributions':contributions,'coverage':{'documented':covered,'total':total},'method':'Required 70%, preferred 30%; met 1, partial 0.5, unknown or not met 0. When only one group exists it contributes 100%. Eligibility, responsibilities, general competencies, and job logistics are excluded.'}

def posting_catalogs(job):
    """Verify server-owned sources before spending a provider request."""
    from . import role_alignment
    from .ai import valid_quote
    catalogs={'requirements':job_parser.criteria(job),'duty_assessments':role_alignment.catalog(job)}
    for rows in catalogs.values():
        if len({row['id'] for row in rows})!=len(rows) or any(not source_quote_valid(row['source'],job) for row in rows):
            raise ServiceError('The posting criteria could not be traced to the saved posting. Review the posting before comparing; no OpenAI request was started.')
    return catalogs

def attach_posting_sources(output,catalogs):
    """Join exact catalog IDs to trusted source text; never repair applicant evidence."""
    result={**output}
    for field,rows in catalogs.items():
        by_id={row['id']:row for row in rows};seen=set();assessed=[]
        for assessment in output.get(field,[]):
            identity=assessment['criterion_id'];criterion=by_id.get(identity)
            if not criterion or identity in seen:
                raise ServiceError('The comparison used an unknown or repeated posting criterion. No result was saved; your previous comparison remains available.')
            seen.add(identity)
            assessed.append({**assessment,'keyword':criterion['text'],'job_quote':criterion['source'],'kind':criterion['kind'],'importance':criterion['importance'],'classification_reason':criterion['classification_reason']})
        result[field]=assessed
    return result

def evidence_catalog(retrieved,profile):
    """Exact passages from this comparison's confirmed, account-owned records only.

    Keep the existing evidence rendering, including legacy array/credential handling.
    Split only at actual line boundaries, never punctuation or subject-name commas.
    IDs include content so changed passages cannot silently reuse old references.
    """
    from .ai import experience_fields
    professional=[];eligibility=[]
    def passage(record_id,field,text):
        identity=hashlib.sha256((record_id+'\0'+field+'\0'+text).encode()).hexdigest()[:32]
        return {'source_id':'evidence:'+identity,'record_id':record_id,'field':field,'quote':text}
    for record in retrieved:
        if record['kind']!='experience':continue
        for field,text in experience_fields(record['data']).items():
            seen=set()
            for line in text.splitlines():
                if not line.strip() or line in ('[]','{}') or line in seen:continue
                seen.add(line);professional.append(passage(record['id'],field,line))
    for field in PRIVATE_FIELDS:
        if profile.get(field):eligibility.append(passage('profile:'+field,field,field+' = '+profile[field]))
    return {'professional':professional,'eligibility':eligibility}

def attach_evidence_sources(output,catalog):
    """Resolve IDs without fuzzy quote repair or promoting private data to experience."""
    professional={r['source_id']:r for r in catalog['professional']}
    private={r['source_id']:r for r in catalog['eligibility']}
    result={**output}
    for field in ('requirements','duty_assessments','recommendations','keywords'):
        rows=[]
        for row in output.get(field,[]):
            evidence=[]
            for ref in row['evidence']:
                identity=ref.get('source_id');source=professional.get(identity)
                if identity in private:
                    if field!='requirements' or row['kind']!='eligibility':
                        raise ServiceError('The comparison used private eligibility evidence outside an eligibility assessment. No result was saved.')
                    source=private[identity]
                if not source:
                    raise ServiceError('The comparison cited an unavailable Profile passage. No result was saved; your previous comparison remains available.')
                if field=='recommendations' and source['record_id']!=row['record_id']:
                    raise ServiceError('A content recommendation cited another record. No result was saved.')
                value={'record_id':source['record_id'],'quote':source['quote']}
                if value not in evidence:evidence.append(value)
            rows.append({**row,'evidence':evidence})
        result[field]=rows
    return result

def rewrite_catalog(retrieved,evidence):
    """Only editable professional wording and selected attributed writing guidance."""
    sources=[r for r in evidence['professional'] if r['field'] in EDITABLE_FIELDS]
    guides=[]
    for row in retrieved:
        if row['kind']!='guidance' or not row['data'].get('text','').strip():continue
        text=row['data']['text']
        identity=hashlib.sha256((row['id']+'\0'+text).encode()).hexdigest()[:32]
        guides.append({'source_id':'guidance:'+identity,'guide_id':row['id'],'quote':text})
    return {'sources':sources,'guidance':guides}

def attach_rewrite_sources(output,catalog):
    """Invalid optional rewrites are omitted, never applied or allowed to erase assessments."""
    sources={r['source_id']:r for r in catalog['sources']}
    guides={r['source_id']:r for r in catalog['guidance']}
    accepted=[];omitted=0
    for row in output.get('suggestions',[]):
        source=sources.get(row.get('source_id'));guide=guides.get(row.get('guidance_source_id'))
        if not source or not guide:
            omitted+=1;continue
        accepted.append({'record_id':source['record_id'],'original':source['quote'],'proposed':row['proposed'],'reason':row['reason'],'guide_id':guide['guide_id'],'guide_quote':guide['quote']})
    return {**output,'suggestions':accepted,'omitted_suggestions':omitted}


def validate(output,job,retrieved,profile):
    from .ai import valid_quote, experience_text, validate_analysis, normalized
    records={r['id']:experience_text(r['data']) for r in retrieved if r['kind']=='experience'}
    records.update({'profile:'+k:k+' = '+profile[k] for k in PRIVATE_FIELDS if profile.get(k)})
    catalog=job_parser.criteria(job);assessed={}
    for r in output['requirements']:
        if not source_quote_valid(r['job_quote'],job): raise ServiceError('A comparison requirement did not cite the posting. Retry the comparison.')
        for e in r['evidence']:
            if e['record_id'] not in records or not valid_quote(e['quote'],records[e['record_id']]): raise ServiceError('A comparison reference could not be verified. No result was saved.')
        if r.get('criterion_id') and r['criterion_id'] not in {c['id'] for c in catalog}:raise ServiceError('The comparison used a criterion outside the posting catalog.')
        candidates=[c for c in catalog if (r.get('criterion_id')==c['id'] or valid_quote(r['job_quote'],c['source']))]
        if not candidates:continue  # Responsibilities and competencies cannot enter a denominator.
        words=set(re.findall(r'\w+',r['keyword'].casefold()))
        c=max(candidates,key=lambda c:1000*(c['id']==r.get('criterion_id'))+len(words&set(re.findall(r'\w+',c['text'].casefold())))+2*(c['importance']==r['importance']))
        if c['id'] in assessed:continue
        r={**r,'criterion_id':c['id'],'keyword':c['text'],'job_quote':c['source'],'kind':c['kind'],'importance':c['importance'],'classification_reason':c['classification_reason']}
        if any(e['record_id'].startswith('profile:') for e in r['evidence']) and c['kind']!='eligibility':raise ServiceError('Private work status cannot support a resume qualification.')
        if r['status'] in ('supported','partial','not_met') and not r['evidence']: raise ServiceError('A match or conflict had no evidence. Retry the comparison.')
        # An accepted degree is known; uncertainty can only concern other enrollment conditions.
        if c['kind']=='eligibility' and re.search(r'master',c['text'],re.I):
            if any(re.search(r'master',records[e['record_id']],re.I) for e in r['evidence'] if not e['record_id'].startswith('profile:')):
                r['degree_program_match']='Master’s programs are explicitly accepted, and your Profile lists a master’s program. Any remaining question concerns enrollment or timing, not whether this degree type is accepted.'
            if re.search(r'(?:accept|allow|eligible|eligibility).{0,55}master|master.{0,55}(?:accept|allow)',r['question'],re.I):
                r['question']='Does your enrollment and graduation timeline meet the posting’s stated timing requirement?'
        assessed[c['id']]=r
    requirements=[assessed.get(c['id'],{'criterion_id':c['id'],'keyword':c['text'],'job_quote':c['source'],'kind':c['kind'],'importance':c['importance'],'status':'unknown','evidence':[],'explanation':'This posting criterion was not assessed. There is not enough information to award documented credit.','question':'','classification_reason':c['classification_reason']}) for c in catalog]
    # Citizenship is self-reported private context, never inferred from work authorization.
    for r in requirements:
        if r['kind']=='eligibility' and re.search(r'\b(?:U\.?S\.?|United States)\s+citizen',r['keyword'],re.I) and not re.search(r'\b(?:or|national|resident)\b',r['keyword'],re.I):
            answer=profile.get('us_citizen','')
            r.update({'status':{'yes':'supported','no':'not_met'}.get(answer,'unknown'),'evidence':[{'record_id':'profile:us_citizen','quote':'us_citizen = '+answer}] if answer in ('yes','no') else [],'explanation':{'yes':'Your private Profile answer confirms U.S. citizenship. This eligibility condition is excluded from qualification scoring.','no':'Your private Profile answer establishes a conflict with this stated citizenship restriction. This is separate from work authorization and qualifications.'}.get(answer,'U.S. citizenship has not been confirmed in your private Profile. Work authorization does not establish citizenship.'),'question':''})
    output['requirements']=requirements
    from . import role_alignment
    role_alignment.validate(output,job,records)
    for d in output['job_details']:
        if d['job_quote'] and not valid_quote(d['job_quote'],job['description']): raise ServiceError('A job detail did not cite the posting.')
        if d['value']!='Not stated' and not d['job_quote']: raise ServiceError('A job detail had no posting evidence.')
    details={d['field']:d for d in output['job_details']}
    output['job_details']=[details.get(k,{'field':k,'value':'Not stated','job_quote':''}) for k in ('location','onsite','hours','schedule','dates')]
    for recommendation in output['recommendations']:
        if recommendation['record_id'] not in records or recommendation['record_id'].startswith('profile:'): raise ServiceError('A recommendation referred to an unavailable record.')
        if not recommendation['evidence']: raise ServiceError('A content recommendation had no source evidence.')
        for e in recommendation['evidence']:
            if e['record_id']!=recommendation['record_id'] or not valid_quote(e['quote'],records[e['record_id']]): raise ServiceError('A content recommendation could not be grounded.')
    # An optional wording edit cannot invalidate a source-verified comparison.
    # Keep every original factual/negation/attribution check; withhold failed edits.
    verified=[];omitted=output.get('omitted_suggestions',0)
    for suggestion in output['suggestions']:
        try:validate_analysis({'requirements':[],'suggestions':[suggestion]},job,retrieved)
        except ServiceError:omitted+=1
        else:verified.append(suggestion)
    output['suggestions']=verified;output['omitted_suggestions']=omitted
    for keyword in output.get('keywords',[]):
        if not valid_quote(keyword['job_quote'],job['description']) or not valid_quote(keyword['term'],keyword['job_quote']):raise ServiceError('A keyword did not quote the posting.')
        for e in keyword['evidence']:
            if e['record_id'].startswith('profile:') or e['record_id'] not in records or not valid_quote(e['quote'],records[e['record_id']]):raise ServiceError('A keyword had invalid Profile evidence.')
    output['score']=score(requirements);output['schema_version']=3
    output['posting_hash']=job_parser.posting_hash(job)
    return output
