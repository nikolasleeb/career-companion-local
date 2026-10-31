"""Public-subject research routing. Never derive public queries from account evidence."""
import re
from . import db

CONVERSATIONAL_STYLE = """ Reply like a helpful person in a text conversation: give the direct answer first in concise, natural paragraphs. Avoid report-style introductions, Markdown headings, bold or emphasis markers, and tables. Use lists or code formatting when the user requests them; otherwise prefer ordinary prose. Ask a useful follow-up question only when it helps. Put source citations in references, not Markdown citation syntax in answer. Preserve necessary source qualifications and uncertainty without turning the reply into a report. """
SUBJECT_INSTRUCTIONS = """ For research, return research_subjects containing only the public names or career subjects explicitly named in the current user question, without search instructions. research_topics may paraphrase the requested search; they need not appear verbatim in the question. Do not choose a subject from Profile, goals, Work Styles, application answers or retrieved passages. For an elliptical follow-up, use established_public_subject if supplied; an explicit new subject takes precedence. If a name is ambiguous (for example Epic could mean different companies), set research_clarification=true and ask which subject the user means; do not research yet. Never silently substitute a Profile topic. """
ALIASES = {'aws': ('AWS', 'Amazon Web Services'), 'amazon web services': ('AWS', 'Amazon Web Services'),
           'microsoft': ('Microsoft',), 'google': ('Google',), 'apple': ('Apple',),
           'amazon': ('Amazon',), 'ibm': ('IBM',), 'nvidia': ('NVIDIA',), 'salesforce': ('Salesforce',)}
INTENT = re.compile(r'\b(?:culture|workplace|work[- ]life|management|mentoring|employee|working there)\b', re.I)
FOLLOWUP = re.compile(r'\b(?:it|its|they|their|there|that|those|them|same|more|what about|how about|and|compare|sources?|evidence|tell me)\b', re.I)
STOP = {'research','a','an','the','company','companys','culture','workplace','what','how','is','are','about','tell','me','please','current','latest','its','their','them','there','it','that','sources','evidence','and','compare','with','for','at','of','on','in','do','does','can','you','i','my','more','please','could','would','why','which','where','when','you','can','tell','me','information','working','work','life','balance','employees','employee','accounts','independent','official'}
PRIVATE = re.compile(r'@|password|api.?key|citizenship|visa|disab|veteran|sponsor|religion|confidential|private|compensation|salary offer|\d{8}|sk[-_]', re.I)

def words(value):
 return re.findall(r"[a-z0-9]+", value.casefold())

def contains(text, subject):
 return bool(re.search(r'(?<![a-z0-9])'+re.escape(subject)+r'(?![a-z0-9])',text,re.I))

def safe_subject(value, question, private):
 if not isinstance(value,str):return False
 value=value.strip()
 return bool(2<=len(value)<=100 and len(words(value))<=10 and re.fullmatch(r"[\w &+.'’/-]+",value) and
             not PRIVATE.search(value) and not re.search(r'\b(?:my|your|our|mine|offer|profile|assessment|questionnaire)\b',value,re.I) and not any(contains(value,s) for s in private) and
             contains(question,value) and any(w not in STOP for w in words(value)))

def previous_brief(history, user=None):
 # Only server-validated research subjects establish a subject, never Profile text.
 for index in range(len(history)-1,-1,-1):
  data=history[index].get('data',history[index])
  if data.get('role')=='assistant':
   prior=data.get('research_diagnostics',{})
   if prior.get('subjects'):return prior
   # Legacy chats have no diagnostics. Re-read only the preceding user's public
   # subject, never the old answer, source catalog or Profile-derived search topics.
   if user:
    question=next((r.get('data',r).get('content','') for r in reversed(history[:index]) if r.get('data',r).get('role')=='user'),'')
    legacy=brief(question,[],[],user)
    if legacy['subjects']:return legacy
   return None
 return None

def brief(question, suggested, history, user):
 settings=db.settings(user)
 private=[str(settings[k]).strip() for k in ('name','email','phone','contact') if settings.get(k)]
 candidates=[]
 # Public aliases and explicit standalone subject lines also cover the exact starter prompt.
 for alias,names in ALIASES.items():
  if contains(question,alias):candidates.append(next((n for n in names if contains(question,n)),names[0]))
 for line in question.splitlines():
  if re.match(r'^\s*[-•]\s+',line):candidates.append(re.sub(r'^\s*[-•]\s+','',line).strip())
 candidates.extend(suggested or [])
 # Names supplied after a clear subject cue, including public events and providers.
 for match in re.finditer(r'(?:culture\s+(?:at|of)|research(?:\s+about)?|conference called|certification called)\s+([A-Z][\w &+.-]{1,90})',question):
  candidates.append(match.group(1).strip(' .'))
 subjects=[]
 for candidate in candidates:
  if safe_subject(candidate,question,private) and candidate.casefold() not in [s.casefold() for s in subjects]:
   # Do not retain a query phrase when a shorter literal subject already covers it.
   if not any(contains(candidate,s) for s in subjects):subjects.append(candidate.strip())
 subjects=subjects[:3]
 previous=previous_brief(history,user)
 purpose=next((kind for kind,pattern in [('company_culture',INTENT),('certification',re.compile(r'certif|exam',re.I)),('event',re.compile(r'conference|workshop|agenda|registration|summit',re.I)),('pricing',re.compile(r'prices?|cost|subscription',re.I)),('labor_market',re.compile(r'jobs?|hiring|salary|wages?|labor market|trends?',re.I))] if pattern.search(question)),'general')
 topical_change=bool(re.search(r'\b(?:instead|switch|new topic|different|resume|cover letter|python|sql|my project|my goals)\b',question,re.I))
 # Inherit only a short referential continuation. A long new question needs its own subject.
 reference=bool(re.search(r'\b(?:it|its|they|their|there|that|those|them|same|more)\b',question,re.I))
 aspect_words={'balance','mentoring','workload','leadership','management','reports','reporting','accounts','sources','source','evidence','learning','opportunities','certifications','requirements','cost','prices','hiring','jobs','salary','wages','pay','length'}
 aspect_followup=bool(FOLLOWUP.search(question)) and all(w in STOP|aspect_words for w in words(question))
 if not subjects and previous and (reference or aspect_followup) and len(words(question))<=24 and not topical_change:
  # Unrecognized proper names must be clarified instead of silently using the old company.
  unknown=[w for w in re.findall(r'\b[A-Z][a-zA-Z0-9]+\b',question) if w.casefold() not in STOP|{'why','which','where','when','could','would','also','but','thanks'}]
  if not unknown:
   subjects=previous['subjects'];purpose=previous.get('purpose','general') if purpose=='general' else purpose
 # Apple/Amazon need company context; known AWS is already unambiguous.
 ambiguous=any(s.casefold() in ('apple','amazon') for s in subjects) and not (INTENT.search(question) or re.search(r'company|employer|inc\b|jobs?|hiring',question,re.I) or previous and previous.get('purpose')=='company_culture')
 if ambiguous:subjects=[]
 suffix={'company_culture':' workplace culture official company information independent reporting employee accounts','certification':' certifications exams official requirements','event':' event agenda dates organizer workshops','pricing':' official pricing current costs','labor_market':' employment hiring labor market current evidence'}.get(purpose,'')
 topics=[s+suffix for s in subjects]
 return {'subjects':subjects,'purpose':purpose,'topics':topics,'clarification':not bool(subjects)}

def relevant(chunk, brief):
 text=chunk.get('title','')+' '+chunk.get('text','')
 subjects=brief.get('subjects',[])
 def matches(subject):
  aliases=ALIASES.get(subject.casefold(),(subject,))
  return any(contains(text,a) for a in aliases)
 if not any(matches(s) for s in subjects):return False
 if brief.get('purpose')=='company_culture':
  return bool(re.search(r'\b(?:culture|workplace|employees?|mentoring|management|work[- ]life|workload|leadership principles|working conditions|workers?|collaboration|benefits|burnout|layoffs?|return to office)\b',chunk.get('text',''),re.I))
 return True

def diagnostics(data, brief):
 chunks=[c for c in data.get('chunks',[]) if relevant(c,brief)]
 urls={c['url'] for c in chunks}
 outcome='relevant_sources' if len(urls)>=2 else 'limited_evidence' if chunks else 'unavailable'
 return {**brief,'outcome':outcome,'relevant_pages':len(urls),'checked_at':data.get('checked_at'),
         'warnings':data.get('warnings',[]),'web_search_performed':data.get('web_search_performed',False)}

def catalog_sources(record, brief):
 chunks=[c for c in record['data'].get('chunks',[]) if relevant(c,brief)]
 # Interleave pages so the first page cannot consume the whole research allowance.
 pages={}
 for chunk in chunks:pages.setdefault(chunk['url'],[]).append(chunk)
 ordered=[page[i] for i in range(max((len(p) for p in pages.values()),default=0)) for page in pages.values() if i<len(page)][:10]
 return [{'source_id':v['chunk_id'],'record_id':record['id'],'kind':'web','label':v['title'],'url':v['url'],
          'checked_at':v['checked_at'],'text':v['text'],'revision':record['updated_at']} for v in ordered]

def budget(sources, pinned=()):
 # Same workspace context limits; prioritize explicit selections then relevant public evidence.
 ordered=([s for s in sources if s['record_id'] in pinned]+[s for s in sources if s['kind'].startswith('explicit_')]+
          [s for s in sources if s['kind']=='web']+sources)
 result=[];seen=set();remaining=26000
 for s in ordered:
  if s['source_id'] in seen or len(result)>=18:continue
  if len(s['text'])>remaining:continue
  result.append(s);seen.add(s['source_id']);remaining-=len(s['text'])
 return result
