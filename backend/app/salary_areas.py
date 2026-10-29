"""Shared, local salary geography matching. Aliases select official areas only."""
import re,unicodedata
from functools import lru_cache
from . import career_wages
ALIASES={'metro:47900':['dmv','nova','northern virginia','washington dc','washington d c','washington']}
def norm(value):return ' '.join(re.findall(r'\w+',unicodedata.normalize('NFKC',value).casefold()))
@lru_cache(maxsize=1)
def catalog():
 raw=career_wages.areas();states={a['state']:a['title'] for a in raw if a['type']=='state'}
 out=[]
 for a in raw:
  suffix=re.search(r', ([A-Z]{2}(?:-[A-Z]{2})*)$',a['title'])
  codes=suffix.group(1).split('-') if suffix else [a['state']] if a['state'] in states else []
  names=[states[c] for c in codes if c in states]
  out.append({**a,'state_codes':codes,'state_names':names,'aliases':ALIASES.get(a['id'],[]),'search_text':norm(' '.join([a['title'],*codes,*names,*ALIASES.get(a['id'],[])]))})
 return out

def search(query='',limit=20):
 q=norm(query);rows=catalog();state_matches={a['state'] for a in rows if a['type']=='state' and (norm(a['title'])==q or norm(a['state'])==q)} if q else set()
 alias_matches={a['id'] for a in rows if q and q in [norm(v) for v in a['aliases']]}
 selected=[a for a in rows if not q or a['id'] in alias_matches or (bool(state_matches & set(a['state_codes'])) if state_matches else q in a['search_text'])]
 return sorted(selected,key=lambda a:(norm(a['title'])!=q,a['id'] not in alias_matches,{'national':0,'state':1,'metro':2,'nonmetro':3}[a['type']],a['title']))[:limit]
