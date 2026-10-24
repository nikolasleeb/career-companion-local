"""Posting-grounded duties, separate from prerequisite scoring and eligibility."""
import hashlib
import re
from . import job_parser
from .network import ServiceError

VERSION=1

def catalog(job):
    rows=job_parser.organize(job)['sections']['responsibilities']
    if not rows:
        # Unheaded descriptions still contain useful duties. Keep an exact quote;
        # do not promote employer marketing, benefits or generic traits to duties.
        rows=[]
        for p in job_parser.paragraphs(job.get('description','')):
            if p['group'] not in ('intro','summary'):continue
            if re.match(r"^(?:(?:in this role[, ]+)?you (?:will|would)|you[’']ll|(?:your )?responsibilities include|(?:build|develop|analyze|analyse|prepare|document|collaborate|design|maintain|support|work with)\b)",p['text'],re.I):
                rows.append({'id':hashlib.sha256(('responsibilities|'+p['text'].casefold()).encode()).hexdigest()[:20],'text':p['text'],'source':p['quote']})
    return [{**r,'kind':'responsibility','importance':'unclear','classification_reason':'A stated job duty used to assess relevant experience and guide resume content; not an explicit prerequisite and excluded from the qualification score.'} for r in rows]

def question(row):
    text=row.get('text',row.get('keyword',''))
    if re.search(r'train|validat|machine learning models|predictive',text,re.I):
        prompt='Have you built, trained or validated a model in coursework, a project or a job? Describe your own part, the data and methods you used, and how you checked the results. If not, say so.'
    elif re.search(r'document|report|present|communicat',text,re.I):
        prompt='Have you written documentation, reports or analytical summaries, or presented findings? What did you personally produce, who used it, and what did it help them understand or do?'
    elif re.search(r'data|dataset|clean|sensor|etl',text,re.I):
        prompt='Describe a relevant dataset you prepared or analyzed. What problem did you address, which methods did you use, and what was your individual contribution or supported outcome?'
    elif re.search(r'collaborat|partner|team|work with',text,re.I):
        prompt='Describe a time you worked with technical or nontechnical partners on a problem. What decisions or work were yours, how did you use their feedback, and what happened?'
    else:
        prompt='Have you done comparable work for this duty: “'+text+'”? Describe a concrete example, your own contribution, the methods and audience, and any outcome you can support.'
    return {'text':prompt,'criterion_id':row.get('id',row.get('criterion_id')),'topic':'job_duty','job_quote':row.get('source',row.get('job_quote','')),'reason':'Strengthen evidence for this job duty: '+text}

def unassessed(row):
    return {'criterion_id':row['id'],'keyword':row['text'],'job_quote':row['source'],'kind':'responsibility','importance':'unclear','status':'unknown','evidence':[],'explanation':'This duty has not been assessed against your Profile. Rerun the comparison for a source-backed assessment.','question':question(row)['text'],'classification_reason':row['classification_reason'],'assessment_complete':False}

def rows(analysis,job):
    saved={r['criterion_id']:r for r in (analysis or {}).get('duty_assessments',[]) if r.get('criterion_id')}
    return [saved.get(c['id'],unassessed(c)) for c in catalog(job)]

def validate(output,job,records):
    from .ai import valid_quote
    duties=catalog(job);by_id={c['id']:c for c in duties};checked={}
    for row in output.get('duty_assessments',[]):
        c=by_id.get(row['criterion_id'])
        if not c or row['criterion_id'] in checked:raise ServiceError('A duty assessment used an unknown or repeated posting reference. No comparison was saved.')
        if not valid_quote(row['job_quote'],c['source']):raise ServiceError('A duty assessment did not cite its exact posting source.')
        for e in row['evidence']:
            if e['record_id'].startswith('profile:'):raise ServiceError('A job duty cited a private eligibility answer. No comparison was saved.')
            if e['record_id'] not in records:raise ServiceError('A job duty cited an unavailable confirmed experience record. No comparison was saved.')
            if not valid_quote(e['quote'],records[e['record_id']]):raise ServiceError('A job-duty quote did not match its confirmed experience source. No comparison was saved.')
        if row['status']!='unknown' and not row['evidence']:raise ServiceError('A duty match or limitation had no supporting evidence.')
        if row['status']=='not_met' and not any(re.search(r"\b(?:no|not|never|cannot|without|haven.t)\b",e['quote'],re.I) for e in row['evidence']):raise ServiceError('A duty limitation was not established by explicit conflicting evidence. Missing detail is unknown, not a failure.')
        value={**row,'keyword':c['text'],'job_quote':c['source'],'kind':'responsibility','importance':'unclear','classification_reason':c['classification_reason'],'assessment_complete':True}
        if value['status']=='supported':value['question']=''
        elif not value['question'].strip():value['question']=question(c)['text']
        checked[c['id']]=value
    output['duty_assessments']=[checked.get(c['id'],unassessed(c)) for c in duties]
    output['duty_alignment_version']=VERSION
    return output

def initial_questions(analysis,job):
    if not analysis:return []
    qualifications=[{'text':r['question'],'criterion_id':r.get('criterion_id'),'reason':'Clarify this explicit qualification: '+r['keyword'],'job_quote':r['job_quote'],'profile_evidence':r.get('evidence',[]),'project_refs':r.get('project_refs',[])} for r in (analysis or {}).get('requirements',[]) if r.get('kind')=='qualification' and r['status'] in ('partial','unknown','not_met') and r.get('question')]
    gaps=[r for r in rows(analysis,job) if r['status'] in ('partial','unknown','not_met')]
    # Concrete technical and communication gaps come before general team prompts.
    gaps.sort(key=lambda r:(0 if re.search('train|validat|document|report',r['keyword'],re.I) else 1,0 if r['status']=='partial' else 1))
    questions=qualifications[:1]+[{**question(r),'text':r.get('question') or question(r)['text'],'profile_evidence':r.get('evidence',[]),'assessment_explanation':r.get('explanation',''),'project_refs':r.get('project_refs',[])} for r in gaps]+qualifications[1:]
    result=[];seen=set()
    for q in questions:
        key=re.sub(r'\s+',' ',q['text']).strip().casefold()
        if key not in seen:result.append(q);seen.add(key)
    return result[:3]
