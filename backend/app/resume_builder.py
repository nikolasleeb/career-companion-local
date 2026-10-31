"""Source-linked content selection and measured one-page fitting. No hidden AI calls."""
import base64
import copy
import io
import re
from pypdf import PdfReader
from . import documents
from .network import ServiceError

def tokens(text):
    return set(re.findall(r'[a-z][a-z0-9+#]{1,}',text.lower()))-{'the','and','with','this','from','that','your','have','will','work','for','our'}

def rank(text,job): return len(tokens(text)&tokens(job))

def catalog(snapshot,analysis=None):
    job=(snapshot.get('posting_snapshot') or {}).get('description','')
    recommended={r['record_id']:r['reason'] for r in (analysis or {}).get('recommendations',[])}
    rows=[]
    for section in snapshot['sections']:
        for entry in section['entries']:
            # Header facts are applicant evidence too; dates are not content items.
            header={key:entry.get(key,'') for key in ('details','dates','start_date','end_date','expected_graduation','relationship_context')}
            rows.append({**header,'reviewed_answer_sources':copy.deepcopy(entry.get('reviewed_answer_sources',[])),'id':entry['source_id'],'title':entry['title'],'category':entry['category'],'organization':entry.get('organization',''),'bullets':entry['bullets'],'items':entry.get('content_items',[]),'priority':entry.get('priority',rank(entry['title']+' '+' '.join(entry['bullets']),job)+(30 if entry['source_id'] in recommended else 0)+(10 if entry['category']=='education' else 0)),'reason':entry.get('selection_reason',recommended.get(entry['source_id'],'Manual content from your confirmed Profile.'))})
    return rows

def select(snapshot,content,ids):
    result=copy.deepcopy(snapshot)
    for section in result['sections']:
        section['entries']=[e for e in section['entries'] if e['source_id'] in ids]
        for entry in section['entries']:
            allowed=content.get(entry['source_id'],list(range(len(entry['bullets']))))
            entry['bullets']=[v for i,v in enumerate(entry['bullets']) if i in allowed and v.strip()]
            entry['content_items']=[v for i,v in enumerate(entry.get('content_items',[])) if i in allowed and v['text'].strip()]
        section['entries']=[e for e in section['entries'] if e['bullets'] or e['category']=='education']
    from . import linked_project_evidence
    linked_project_evidence.deduplicate(result)
    linked_project_evidence.validate_selected(result)
    result.pop('linked_project_originals',None)  # Restoration catalog stays in the versioned source, not employer document context.
    result['experience_ids']=[e['source_id'] for s in result['sections'] for e in s['entries']]
    result['content']=content
    return result

def render(snapshot):
    word,_=documents.export_resume(snapshot,'docx')
    pdf=documents.docx_pdf(word)
    pages=len(PdfReader(io.BytesIO(pdf)).pages)
    return pages,{'docx':base64.b64encode(word).decode(),'pdf':base64.b64encode(pdf).decode()}

def fit(snapshot, rows, initial=None, protected_item_ids=None, render_fn=None):
    job=(snapshot.get('posting_snapshot') or {}).get('description','')
    protected=set(protected_item_ids or []);measure=render_fn or render
    ordered=sorted(rows,key=lambda r:-r['priority'])
    ids=list(initial['experience_ids']) if initial else [r['id'] for r in ordered if r['category']=='education' or r['bullets']]
    def priority(r,i):
        item=(r.get('items') or [{}]*len(r['bullets']))[i]
        if 'priority' in item:return item['priority']
        return rank(r['bullets'][i],job)*5+({'skill':45,'certification':40,'gpa':30,'course':20,'education_note':-100,'url':-10}.get(item.get('field'),25))
    content=copy.deepcopy(initial['content']) if initial else {r['id']:[i for i in range(len(r['bullets'])) if r['bullets'][i].strip() and (r.get('items') or [{}]*len(r['bullets']))[i].get('field')!='education_note'] for r in ordered if r['id'] in ids}
    def removable(r,i):
        if r.get('items') and r['items'][i]['item_id'] in protected:return False
        remaining=[j for j in content.get(r['id'],[]) if j!=i]
        if not remaining:return False
        if r['category']=='project' and r.get('items'):
            return any(r['items'][j]['field'] in ('description','contribution','accomplishment') for j in remaining)
        if r['category']=='skills' and r.get('items') and any(v['field'] in ('skill','certification') for v in r['items']):
            return any(r['items'][j]['field'] in ('skill','certification') for j in remaining)
        return True
    removed=[]
    # Each iteration removes exactly one item or one whole record, never all bullets in a batch.
    for attempt in range(sum(len(r['bullets']) for r in rows)+len(rows)+1):
        proposal=select(snapshot,content,ids)
        pages,_=measure(proposal)
        if pages==1:break
        candidates=[(priority(r,i)+r['priority']/10,r['id'],i) for r in ordered if r['id'] in ids for i in content.get(r['id'],[]) if removable(r,i)]
        if candidates:
            _,rid,i=min(candidates);content[rid].remove(i);removed.append((rid,i))
        elif len(ids)>1:
            removable_ids=[rid for rid in ids if not any(item['item_id'] in protected for item in next(r for r in rows if r['id']==rid).get('items',[]))]
            if not removable_ids:raise ServiceError('The required content does not fit one readable page. Your protected selections and previous draft are intact; shorten other content before retrying.')
            rid=min(removable_ids,key=lambda rid:next(r['priority'] for r in rows if r['id']==rid));ids.remove(rid)
        else:raise ServiceError('The remaining record exceeds one page. Shorten its wording or your contact header. Nothing was clipped.')
    else:raise ServiceError('The draft still exceeds one page. Review shorter content; your Profile is unchanged.')
    # Try adding back the most valuable removed items while checking actual layout.
    by_id={r['id']:r for r in rows}
    for rid,i in sorted(removed,key=lambda x:-priority(by_id[x[0]],x[1])):
        if rid not in ids:continue
        content[rid]=sorted(content[rid]+[i])
        if measure(select(snapshot,content,ids))[0]!=1:content[rid].remove(i)
    proposal=select(snapshot,content,ids);ids=proposal['experience_ids']
    omissions=[{'record_id':r['id'],'title':r['title'],'reason':'Lower priority for this role or the one-page limit.' if r['id'] in ids else 'Omitted to prioritize more relevant, complete evidence.','bullets':[v for i,v in enumerate(r['bullets']) if r['id'] not in ids or i not in content.get(r['id'],[])]} for r in rows if r['id'] not in ids or len(content.get(r['id'],[]))<len(r['bullets'])]
    return {'experience_ids':ids,'content':content,'pages':1,'omitted':omissions}
