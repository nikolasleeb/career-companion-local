"""One deterministic catalog for matching, field bundles and Profile suggestions."""
import json,re
from pathlib import Path
from . import db
CATALOG=json.loads(Path(__file__).with_name('role_catalog.json').read_text())
VERSION=CATALOG['version']
GROUPS=CATALOG['groups']
ALIASES={row['label'].casefold():row['aliases'] for row in CATALOG['roles']}
# Legacy custom search spelling remains compatible.
ALIASES['data analyst']=ALIASES['data analysis']
def phrase(term,text):
    return bool(re.search(r'(?<!\w)'+re.escape(term.casefold()).replace(r'\ ',r'\s+')+r'(?!\w)',text.casefold()))
def suggestions(user):
    rows=[r['data'] for r in db.list_entities(user,'experience') if r['data'].get('confirmed')]
    primary=[];secondary=[]
    for d in rows:
        if d.get('category')=='education':
            primary.append(' '.join(str(d.get(k) or '') for k in ('degree','major','concentration','title'))+' '+' '.join(d.get('majors') or []))
        elif d.get('category') in ('employment','project','volunteering'):primary.append(str(d.get('title') or ''))
        secondary.append(' '.join(str(d.get(k) or '') for k in ('relevant_courses','tools','description','contribution','accomplishments'))+' '+' '.join(str(s.get('name','')) for s in d.get('skill_items',[])))
    # Only professional fields of confirmed records are inspected. No settings,
    # authorization answers, private vault data or unreviewed imports enter here.
    structured=' '.join(primary);support=' '.join(secondary);ranked=[]
    for i,row in enumerate(CATALOG['roles']):
        direct=sum(1 for term in [row['label'],*row['aliases']] if phrase(term,structured))
        corroboration=sum(1 for term in set([row['label'],*row['aliases'],*row['support']]) if phrase(term,support))
        if direct or corroboration>=2:ranked.append((-(100*direct+min(corroboration,20)),i,row['label']))
    return [label for _,_,label in sorted(ranked)[:4]]
