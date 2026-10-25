"""Posting-specific US location matching. Region names are explicit groups, not guesses."""
import re
STATES=dict(v.split(':',1) for v in 'AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|DC:District of Columbia|FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming'.split('|'))
REGIONS={
 'East Coast':'ME NH VT MA RI CT NY NJ PA DE MD DC VA NC SC GA FL',
 'Northeast':'ME NH VT MA RI CT NY NJ PA',
 'Southeast':'DE MD DC VA WV NC SC GA FL KY TN AL MS AR LA',
 'West Coast':'WA OR CA',
 'Midwest':'OH MI IN IL WI MN IA MO ND SD NE KS',
 'Southwest':'AZ NM OK TX',
 'Mountain West':'MT ID WY NV UT CO AZ NM',
 'Pacific Northwest':'WA OR ID',
 'New England':'ME NH VT MA RI CT',
 'Mid-Atlantic':'NY NJ PA DE MD DC VA WV',
}
NATIONWIDE={'united states','us','usa','nationwide','anywhere','remote','anywhere in the us'}
NAMES={name.casefold():code for code,name in STATES.items()}
PATTERN=r'\b(?:'+'|'.join(re.escape(n) for n in sorted(STATES.values(),key=len,reverse=True))+r')\b'
def region(value):return next((name for name in REGIONS if name.casefold()==value.strip().casefold().replace('eastern coast','east coast')),None)
def state(value):
 value=value.strip();return value.upper() if value.upper() in STATES else NAMES.get(value.casefold())
ALIASES={'san francisco':'CA','sf office':'CA','nyc':'NY','new york city':'NY','boston':'MA','tucson':'AZ','phoenix':'AZ','seattle':'WA','raleigh':'NC','atlanta':'GA','washington dc':'DC','washington, d.c.':'DC'}
def codes(text):
    text=re.sub(r'\bWashington\s*,?\s*(?:D\.?C\.?|District of Columbia)\b','District of Columbia',text,flags=re.I)
    found={code for name,code in ALIASES.items() if re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',text,re.I)}
    for part in re.split(r';|\n|\s+[/|]\s+',text):
        suffix=re.findall(r',\s*('+'|'.join(STATES)+r')\b',part)
        if suffix:found.update(suffix);continue
        found.update(NAMES[m.group().casefold()] for m in re.finditer(PATTERN,part,re.I))
        found.update(re.findall(r'\b(?:'+'|'.join(STATES)+r')\b',part))
    return found

def canonical(text):
 text=re.sub(PATTERN,lambda m:NAMES[m.group().casefold()].casefold(),text,flags=re.I)
 return re.sub(r'[^a-z0-9]+',' ',text.casefold()).strip()
def matches(job,query):
 """True=verified match, False=known mismatch, None=not enough posting location data."""
 query=query.strip()
 if query.casefold() in NATIONWIDE:return True
 locations=[job.get('location','')]+[str(v.get('location',''))+' '+str(v.get('state','')) for v in job.get('locations',[]) if isinstance(v,dict)]
 located='; '.join(locations);known=codes(located)
 selected=REGIONS[region(query)].split() if region(query) else [state(query)] if state(query) else []
 if selected:return bool(known.intersection(selected)) if known else None
 needle=canonical(query)
 if any(needle and re.search(r'(?<!\w)'+re.escape(needle)+r'(?!\w)',canonical(value)) for value in locations):return True
 if not known:return None
 # A named city with a state establishes a different city. A state-only listing does not.
 for value in locations:
  if codes(value) and canonical(value) not in {c.casefold() for c in codes(value)}:return False
 return None

def provider_location(value):
 name=region(value)
 if name:return ';'.join(STATES[c] for c in REGIONS[name].split())
 if value.strip().casefold() in NATIONWIDE:return ''
 if state(value):return STATES[state(value)]
 parts=value.rsplit(',',1)
 if len(parts)==2 and state(parts[1]):return parts[0].strip()+', '+STATES[state(parts[1])]
 return value.strip()
def options():
 return ['United States',*REGIONS,*STATES.values(),'Tucson, AZ','Phoenix, AZ','Richmond, VA','Washington, DC','New York, NY','Boston, MA','Raleigh, NC','Atlanta, GA','Seattle, WA','San Francisco, CA']
def region_details():return {name:[STATES[c] for c in values.split()] for name,values in REGIONS.items()}
