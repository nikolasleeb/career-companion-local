"""Bundled, attributed writing principles; never applicant evidence or live research."""
import copy
import hashlib
import json
import re
import sqlite3
from . import config

def principles():
    rows=json.loads((config.CONTENT_DIR/'guidance.json').read_text())
    version='writing-guide-'+hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()[:12]
    return {'version':version,'items':rows}

def catalog():
    return principles()

def handbook():
    return json.loads((config.CONTENT_DIR/'writing_handbook.json').read_text())

def writing_sources():
    value=handbook()
    version='writing-sources-'+hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()[:16]
    resources={r['id']:r for r in value['resources']}
    result=[]
    for passage in value['passages']:
        r=resources[passage['resource_id']]
        result.append({'source_id':'writing:'+passage['id'],'record_id':'writing:'+r['id'],
                       'kind':'writing_guidance','label':r['publisher']+' · '+r['title'],
                       'title':r['title'],'publisher':r['publisher'],'url':r['url'],
                       'section':passage['section'],'page':passage['page'],'audience':r['audience'],
                       'content_kind':passage['content_kind'],'reviewed_at':r['reviewed_at'],
                       'revision':version,'text':passage['text'],'status':'reviewed'})
    return result

def rank(sources,query,limit=10):
    terms=list(dict.fromkeys(re.findall(r'[\w+#.-]{2,40}',query.casefold())))[:60]
    match=' OR '.join('"'+v.replace('"','')+'"' for v in terms)
    with sqlite3.connect(':memory:') as c:
        c.execute('CREATE VIRTUAL TABLE passages USING fts5(id UNINDEXED,title,text,tokenize="porter unicode61")')
        c.executemany('INSERT INTO passages VALUES(?,?,?)',[(s['source_id'],s['label']+' '+s.get('section',''),s['text']) for s in sources])
        ids=[r[0] for r in c.execute('SELECT id FROM passages WHERE passages MATCH ? ORDER BY bm25(passages) LIMIT ?',(match,limit))] if match else []
    by_id={s['source_id']:s for s in sources}
    return [by_id[id] for id in ids]

def retrieve(question):
    rows=writing_sources()
    selected=rank(rows,question)
    # Keep both sides of known audience-dependent advice available for comparison.
    if re.search(r'\b(pages?|length|fonts?|margins?|format|conflicts?|contradict\w*|differ\w*)\b',question,re.I):
        selected += [s for s in rows if s['source_id'] in ('writing:eller-format','writing:format-layout') and s not in selected]
    return selected[:12]

def selected(topic):
    value=principles()
    value['items']=[r for r in value['items'] if r.get('topic') in (topic,'formatting') or r['id']=='guide_evidence']
    return copy.deepcopy(value)

# Public writing guidance can be retrieved by the general Coach without expanding
# any account permissions. Only explicit writing questions or scoped follow-ups
# receive these passages; a new unrelated topic does not inherit writing context.
WRITING_TOPIC=re.compile(r"\b(?:r[eé]sum[eé]s?|curricul(?:um|a) vitae|CVs?|cover[ -]?letters?|resume bullets?|ATS|applicant tracking|personal statements?)\b",re.I)
WRITING_FOLLOWUP=re.compile(r"^(?:(?:and |what about |how about )(?:the |its? )?(?:length|fonts?|margins?|format(?:ting)?|tone|wording|bullets?|examples?|sources?|one page|two pages)\b|(?:why|can you|could you) (?:explain|clarify|shorten|expand|rewrite|rephrase|make) (?:it|that|this|them|those)\b|make (?:it|that|this|them)\b|(?:shorten|expand|rephrase|rewrite|clarify) (?:it|that|this|them)\b)",re.I)
def workspace_query(question,history=()):
    if WRITING_TOPIC.search(question):return question
    if not WRITING_FOLLOWUP.search(question.strip()):return ''
    if not history:return ''
    # Only the most recent answer can establish follow-up scope. Do not revive
    # an older writing topic after the conversation has moved elsewhere.
    last=history[-1]['data']
    if last.get('role')!='assistant' or not any(s.get('kind')=='writing_guidance' for s in last.get('source_snapshot',[])):return ''
    previous=next((r['data']['content'] for r in reversed(history[:-1]) if r['data'].get('role')=='user'), '')
    return previous[:1200]+'\n'+question if WRITING_TOPIC.search(previous) else 'Resume and cover-letter writing\n'+question

def with_workspace_sources(sources,question,history=(),pinned=()):
    query=workspace_query(question,history)
    if not query:return sources
    writing=retrieve(query)
    # Prioritize explicit pins, then relevant guidance and account passages,
    # within the existing general-Coach count and character budgets.
    candidates=[s for s in sources if s['record_id'] in pinned]+writing+[s for s in sources if s['record_id'] not in pinned]
    result=[];seen=set();used=0
    for source in candidates:
        if source['source_id'] in seen:continue
        size=len(source['text'])
        if len(result)>=18:break
        if used+size>26000:continue
        result.append(source);seen.add(source['source_id']);used+=size
    return result
