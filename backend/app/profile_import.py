"""Local import comparison. Potential matches are suggestions, never auto-merges."""
import re,hashlib,json
from . import resume_parser

def normal(value):return re.sub(r'[^\w]+',' ',str(value or '').casefold()).strip()
def degree(value):
 value=normal(value)
 for names,key in [({'bs','b s','bsc','bachelor of science'},'bs'),({'ba','b a','bachelor of arts'},'ba'),({'ms','m s','msc','master of science'},'ms'),({'ma','m a','master of arts'},'ma'),({'mba','master of business administration'},'mba')]:
  if value in names:return key
 return value

def preview(parsed,records):
 result={'_versions':{r['id']:r['updated_at'] for r in records}}
 for entry in parsed.get('entries',[]):
  data=entry['data'];exact=[];matches=[]
  for record in records:
   old=record['data']
   if old.get('category')!=data.get('category'):continue
   if old.get('source_entry_id')==entry['id'] or resume_parser.fingerprint(old)==resume_parser.fingerprint(data):exact.append(record['id']);continue
   org=normal(data.get('organization'));title=degree(data.get('degree') or data.get('title'))
   if org and org==normal(old.get('organization')) and title and title==degree(old.get('degree') or old.get('title')):matches.append(record['id'])
  result[entry['id']]={'exact':exact,'matches':matches}
 return result

def parse(text,kind='resume'):
 if kind!='linkedin_pdf':return resume_parser.parse(text)
 # Normalize recognizable exported-PDF labels and footers only. Keep uncertain
 # material visible; never follow document instructions or fetch profile URLs.
 clean=re.sub(r'(?im)^\s*Page\s+\d+\s+(?:of|/)\s*\d+\s*$','',text)
 clean=re.sub(r'(?im)^\s*Top Skills\s*$','Skills',clean)
 clean=re.sub(r'(?im)^\s*Contact\s*$','',clean)
 parsed=resume_parser.parse(clean);parsed['text_hash']=hashlib.sha256(text.encode()).hexdigest();parsed['parser_version']=resume_parser.VERSION+'-linkedin1'
 # LinkedIn lists employer, role, dates. The ordinary resume parser expects role
 # then employer. Rebuild only blocks with an explicit, recognizable date range.
 lines=clean.splitlines();active=False;body=[]
 for line in lines:
  kind=resume_parser.heading(line)
  if kind=='employment':active=True;continue
  if active and kind:break
  if active and line.strip():body.append(line.strip())
 dated=[i for i,line in enumerate(body) if resume_parser.DATE_RANGE.search(line) and len(line)<180]
 entries=[];cursor=0
 for n,index in enumerate(dated):
  prefix=body[cursor:index]
  if len(prefix)<2:continue
  employer,title=prefix[-2:]
  if not resume_parser.short_title(employer) or not resume_parser.short_title(title):continue
  next_index=dated[n+1] if n+1<len(dated) else len(body)
  end=max(index+1,next_index-2) if n+1<len(dated) else len(body)
  raw='\n'.join(body[cursor:end]);ordered=title+' | '+employer+' | '+body[index]+'\n'+'\n'.join(body[index+1:end])
  one=resume_parser.parse('Experience\n'+ordered)
  if len(one['entries'])!=1:continue
  value=one['entries'][0];value['source_text']=raw;value['id']=hashlib.sha256(('linkedin-employment\n'+raw).encode()).hexdigest()[:24];entries.append(value);cursor=end
 if dated and len(entries)==len(dated):parsed['entries']=[e for e in parsed['entries'] if e['data']['category']!='employment']+entries
 parsed['warnings'].append('LinkedIn PDFs may omit details or mix columns. Review employer, role, dates and credentials; uncertain passages remain available in the source view.')
 return parsed

def version(kind):return resume_parser.VERSION+('-linkedin1' if kind=='linkedin_pdf' else '')
