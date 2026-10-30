"""Versioned learning metadata. No provider fetches or AI calls occur at runtime."""
import json,re,unicodedata
from functools import lru_cache
from pathlib import Path

def normalize(value):return ' '.join(re.findall(r'[\w+#]+',unicodedata.normalize('NFKC',str(value)).casefold()))
@lru_cache(maxsize=1)
def data():return json.loads(Path(__file__).with_name('skills_catalog.json').read_text())
@lru_cache(maxsize=1)
def index():return {s['id']:s for s in data()['skills']}
@lru_cache(maxsize=1)
def aliases():
 result={}
 for s in data()['skills']:
  for name in [s['id'],s['label'],*s.get('aliases',[])]:
   n=normalize(name)
   if n in result and result[n]!=s['id']:raise ValueError('Ambiguous learning alias: '+name)
   result[n]=s['id']
 return result
def resolve(value):return aliases().get(normalize(value))
def refs(values):
 seen=set();result=[]
 for value in values:
  identity=resolve(value);key=identity or normalize(value)
  if not key or key in seen:continue
  seen.add(key);result.append({'id':identity,'label':index()[identity]['label'] if identity else str(value).strip()[:150]})
 return result
