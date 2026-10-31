"""Fictional deterministic provider responses shared by optimizer boundary tests."""
import copy

def strategy(payload):
    facts=payload['professional_evidence']['facts'];posting=payload['posting']['description']
    source=next((f for f in facts if f['field']=='description' and 'Python' in f['text']),next(f for f in facts if f['field']!='header'))
    quote=next((line for line in posting.splitlines() if 'Python' in line),posting.splitlines()[0])
    return {'focus':'Data analysis and digital solutions','rationale':'Prioritize applied technical work and clear communication.','priorities':[{'id':'technical','text':'Apply analytical methods','posting_quote':quote,'kind':'preferred','evidence':'direct','source_ids':[source['id']],'reason':'Reviewed work demonstrates an applied method.','essential':True}], 'constraints':[]}

def composition(payload,mutate=None):
    facts=payload['professional_evidence']['facts'];records=payload['professional_evidence']['records'];entries=[]
    for r in records:
        items=[f for f in facts if f['id'] not in payload.get('user_constraints',{}).get('excluded_source_ids',[]) and f['record_id']==r['record_id'] and f['field'] not in ('header','education_note')]
        if not items and r['category']!='education':continue
        entries.append({'record_id':r['record_id'],'reason':'Relevant evidence for the posting.','items':[{'item_id':f['item_id'],'source_ids':[f['id']],'text':f['text'],'priority':90 if f['field'] in ('skill','certification') else 75,'reason':'Supports the posting.'} for f in items]})
    source=next((f for f in facts if f['field']=='description' and 'Python' in f['text']),next(f for f in facts if f['field']!='header'))
    quote=next((line for line in payload['posting']['description'].splitlines() if 'Python' in line),payload['posting']['description'].splitlines()[0])
    keywords=[{'term':'Python','job_quote':quote,'evidence':[{'record_id':source['record_id'],'quote':source['text']}]},{'term':'SQL','job_quote':quote,'evidence':[]}] if 'Python' in quote and 'SQL' in quote else []
    value={'headline':'Data Science | Python & SQL','headline_evidence':[{'record_id':source['record_id'],'quote':source['text']}],'entries':entries,'omissions':[],'keywords':keywords}
    for lock in payload.get('user_constraints',{}).get('locked_items',{}).values():
        for e in value['entries']:
            if e['record_id']==lock['record_id']:
                e['items']=[i for i in e['items'] if not set(i['source_ids'])&set(lock['source_ids'])]
                e['items'].append({'item_id':'locked','source_ids':lock['source_ids'],'text':lock['text'],'priority':99,'reason':'Explicitly approved wording.'})
    if mutate:mutate(value)
    for e in value['entries']:
        for i in e['items']:i.pop('item_id',None)
    return value
