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
   if old.get('source_entry_id')==entry['id'] or resume_parser.fingerprint(old)==resume_parser.fingerprint(data) or credential_already_saved(data,old):exact.append(record['id']);continue
   org=normal(data.get('organization'));title=degree(data.get('degree') or data.get('title'))
   if org and org==normal(old.get('organization')) and title and title==degree(old.get('degree') or old.get('title')):matches.append(record['id'])
  result[entry['id']]={'exact':exact,'matches':matches}
 return result

def credential_already_saved(data,old):
 # A newly separated credential may already be in an older grouped record.
 # Match all supplied credential fields; never replace the existing group.
 from . import import_values
 proposed=data.get('certification_items',[])
 if len(proposed)!=1:return False
 item=proposed[0]
 return any(all(not value or import_values.same(key,value,saved.get(key,'')) for key,value in item.items()) for saved in old.get('certification_items',[]))

def parse(text,kind='resume'):
 from . import import_values,linkedin_import
 parsed=linkedin_import.parse(text) if kind=='linkedin_pdf' else resume_parser.parse(import_values.repair_wrapped_links(text))
 parsed['text_hash']=hashlib.sha256(text.encode()).hexdigest()
 parsed['parser_version']=version(kind)
 # Retain every distinct address in the contact region, not just the first one.
 contact=text.split('[[LinkedIn sidebar]]',1)[-1] if '[[LinkedIn sidebar]]' in text else text
 if '[[LinkedIn sidebar]]' not in text:
  header=[]
  for line in contact.splitlines():
   if heading_boundary(line):break
   header.append(line)
  contact='\n'.join(header)
 explicit_phone=re.search(r'(?m)(?<!\w)(\+\d[\d ().-]{5,24}\d(?:[ \t]*(?:ext\.?|x)[ \t]*\d+)?)',contact,re.I)
 if explicit_phone:parsed['profile']['phone']=explicit_phone.group(1).strip()
 candidates=list(dict.fromkeys(import_values.EMAIL.findall(contact)))
 if parsed.get('profile',{}).get('email') and parsed['profile']['email'] not in candidates:candidates.insert(0,parsed['profile']['email'])
 parsed['profile_candidates']={'email':candidates} if candidates else {}
 if parsed['profile'].get('name'):
  original_name=parsed['profile']['name'];parsed['profile_candidates']['name']=[original_name];parsed['profile']['name']=import_values.personal_name(original_name)
 if candidates and 'email' not in parsed['profile']:parsed['profile']['email']=candidates[0]
 for entry in parsed['entries']:
  data=entry['data'];uncertain=any(('not confidently' in w or 'not separately' in w) for w in entry.get('warnings',[]))
  if data['category']=='skills' and not (data.get('tools') or data.get('skill_items') or data.get('certification_items')):uncertain=True
  entry['review_state']='needs_review' if uncertain else 'ready'
 return parsed

def heading_boundary(line):return bool(resume_parser.heading(line))

def document_text(document):
 """Use original PDF geometry unless the user has corrected its source text."""
 from . import documents,config
 data=document['data'];text=data['text']
 if data.get('import_source_kind')=='linkedin_pdf' and data.get('format')=='pdf' and not data.get('source_text_corrected') and not (data.get('reviewed') and 'source_text_corrected' not in data):
  path=config.DATA_DIR/'uploads'/document['user_id']/document['id']
  if path.is_file():
   try:
    raw=path.read_bytes()
    if data.get('sha256') and hashlib.sha256(raw).hexdigest()!=data['sha256']:return text
    return documents.linkedin_text(raw) or text
   except Exception:return text
 return text

def parse_document(document):
 parsed=parse(document_text(document),document['data'].get('import_source_kind','resume'))
 parsed['text_hash']=hashlib.sha256(document['data']['text'].encode()).hexdigest()
 return parsed

def version(kind):return resume_parser.VERSION+('-linkedin3' if kind=='linkedin_pdf' else '-polish2')
