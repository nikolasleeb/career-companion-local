"""Local title relevance. Role phrases must not be assembled from unrelated words."""
import re
import unicodedata
from . import role_catalog

LEVEL_WORDS={'junior','entry','level','new','grad','intern','internship','jobs','position'}
# Common compound titles, rather than an arbitrary gap between AI and engineer.
VARIANTS={'ai engineer':('AI/ML engineer','ML/AI engineer','AI software engineer',
 'AI solutions engineer','AI research engineer','AI platform engineer',
 'artificial intelligence engineer','software engineer AI','software engineer applied AI')}

def words(value):
 return re.findall(r'[^\W_]+',unicodedata.normalize('NFKC',str(value)).casefold(),re.UNICODE)

def matcher(queries):
 if isinstance(queries,str):queries=[queries]
 phrases=set()
 for query in queries:
  if not isinstance(query,str):continue
  for alias in [query,*role_catalog.ALIASES.get(query.strip().casefold(),[])]:
   for phrase in (alias,*VARIANTS.get(alias.casefold(),())):
    tokens=tuple(w for w in words(phrase) if w not in LEVEL_WORDS)
    if tokens:phrases.add(tokens)
 def matches(title):
  tokens=words(title)
  return any(tuple(tokens[i:i+len(phrase)])==phrase for phrase in phrases for i in range(len(tokens)-len(phrase)+1))
 return matches

def for_search(data):
 """Historical scope comes from that search, never today's editable preferences."""
 if data.get('discovery_kind')=='for_you':return None
 query=data.get('query')
 if not isinstance(query,dict):return None
 roles=query.get('interests')
 if not isinstance(roles,list) or not any(isinstance(r,str) and r.strip() for r in roles):
  roles=[query['title']] if isinstance(query.get('title'),str) and query['title'].strip() else []
 return matcher(roles) if roles else None

def sql_filter(connection,search):
 matches=for_search(search['data']) if search else None
 if not matches:return ''
 connection.create_function('cc_role_matches',1,matches,deterministic=True)
 return " AND cc_role_matches(json_extract(e.payload,'$.title'))"
