"""Local, source-preserving posting organization. No model or network calls."""
import hashlib
import re

VERSION=5
HEADINGS={
 'required': [r'(?:minimum|basic|required|essential|mandatory) (?:qualifications?|requirements?|skills?|experience)',r'(?:job |position |candidate )?requirements?',r'what you(?: will|’ll|\'ll)? need',r'what you must (?:have|bring)',r'qualifications?',r'what we require'],
 'preferred': [r'(?:preferred|desired|desirable|additional|ideal) (?:qualifications?|requirements?|skills?|experience)',r'nice[ -]to[ -]haves?',r'bonus (?:points|skills)',r'what sets you apart'],
 'responsibilities': [r'(?:key |primary |job |your |role )?(?:responsibilities|duties)',r'(?:the |your )role',r'what you(?: will|’ll|\'ll) do',r'what you(?: will|’ll|\'ll) (?:work on|be doing)',r'your (?:impact|day.to.day)',r'how you(?: will|’ll|\'ll) (?:contribute|make an impact)'],
 'other': [r'core competencies',r'(?:desired )?competencies',r'(?:your |candidate )?profile',r'what you bring',r'who you are',r'(?:what|who) we(?:’re|\'re| are) looking for'],
 'eligibility': [r'(?:work |employment )?authori[sz]ation(?: eligibility)?',r'eligibility',r'(?:visa )?sponsorship',r'eligibility requirements'],
 'location': [r'(?:work |job |office |primary )?location',r'where you(?: will|’ll|\'ll) work',r'where the role is based'],
 'logistics': [r'work (?:model|arrangement|environment)',r'(?:working )?schedule'],
 'pay': [r'(?:salary|pay|compensation)(?: range| information| details)?',r'pay and benefits'],
 'program': [r'(?:the |internship )?program(?: details| overview)?',r'dates and duration'],
 'summary': [r'(?:job |position |role )?(?:description|summary|overview)',r'(?:about )?(?:the|this) (?:job|role|opportunity)',r'the opportunity'],
 'ignore': [r'about .+',r'our (?:values|benefits|company|culture|story)',r'(?:equal employment|equal opportunity).*',r'benefits(?: and perks)?',r'why .+',r'privacy.*',r'legal.*',r'similar (?:jobs|roles)',r'related (?:jobs|roles)',r'how to apply',r'apply now',r'what we believe',r'what we offer',r'our offer.*',r'apply today',r'remind me to(?: apply)?',r'job posting date',r'your future starts here',r'skills you(?:’ll|\'ll) build',r'the experience',r'what you(?:’ll|\'ll) gain.*',r'requesting an accommodation',r'other employment statements',r'apply for this job',r'create an account.*',r'expectation for integrity.*',r'get notified for similar jobs.*']
}
START=re.compile(r'^(?:A history of |Eligible to work|Relocation to |Must relocate |COVID[- ]?19 vaccination|Vaccination|A strong |A willingness |An open.minded |Our behavio[u]?rs |Working towards? |Currently|U\.S\.|US citizenship|Citizenship|Valid|Must|You (?:must|will|have)|Have|Be |Bachelor|Master|Associate|Ph\.?D|BS\b|BA\b|MS\b|Strong|Excellent|Relevant|Practical|Proficiency|Experience|Knowledge|Ability|Demonstrated|Familiarity|Comfortable|Enjoy|Clear|Adaptable|Gain|Present|Participate|At least|Minimum|Enthusiasm|Curiosity|Passion|Proactivity|Dedication|Analyze\b|Collaborate\b|Learn\b|Contribute\b|Develop\b|Build\b|Design\b|Support\b|Maintain\b|Work with|Partner with|Create\b|Assist\b|Communicate\b|Manage\b|Lead\b|Perform\b|Required:|Preferred:)',re.I)
NOISE=re.compile(r'^(?:Save\s*Share\s*Apply externally|SaveShareApply externally|At a glance|Job alerts|Sign in|Log in|Keep looking\s*Apply Now|Apply Now\s*Keep looking|Skip to .+|Back to .+|Apply now|Apply externally|Share|Save job|Page \d+(?: of \d+)?|https?://\S+(?:\s+\d+\s*/\s*\d+)?|\d+\s*/\s*\d+|©.*)$',re.I)
STATES=r'(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)'
CITY=re.compile(r'\b([A-Z][A-Za-z.\'-]*(?:[ \t]+[A-Z][A-Za-z.\'-]*){0,3}),[ \t]*('+STATES+r')\b')

def display_line(value):
    # Browser PDFs can draw bold headings several times at the same position.
    # Normalize presentation only; quotes and original_text retain the raw source.
    value=value.translate(str.maketrans({'ﬀ':'ff','ﬁ':'fi','ﬂ':'fl','ﬃ':'ffi','ﬄ':'ffl','ﬅ':'st','ﬆ':'st'}))
    value=re.sub(r'\s+',' ',value).strip()
    for count in (4,3,2):
        if len(value)%count==0:
            unit=value[:len(value)//count]
            if len(unit)>=3 and re.search(r'[A-Za-z]',unit) and unit*count==value:
                value=unit.strip();break
    value=re.sub(r'^(.{2,100}?[:?])(?:\s*\1){1,}',r'\1',value)
    return value


def career_title(value):
    value=re.sub(r'^Job Application for\s+','',display_line(value),flags=re.I)
    company_first=re.fullmatch(r'(.+?)\s+(?:Careers?|Jobs?)(?:\s+[-–—]\s+|\s*\|\s*)(.+)',value,re.I)
    if company_first:return company_first[2].strip(),company_first[1].strip()
    match=re.fullmatch(r'(.+?)(?:\s+[-–—]\s+|\s*\|\s*)(.+?)\s+(?:Careers?|Jobs?|Career Site|Career Opportunities)',value,re.I)
    if match:return match[1].strip(),match[2].strip()
    match=re.fullmatch(r'(.+?)\s+at\s+([^|]+)(?:\s*\|.*)?',value,re.I)
    if match and len(match[1])<=120 and not re.search(r'[,!?;.]',match[1]) and not re.match(r'^(?:the |a |an )',match[2]):
        return match[1].strip(),re.sub(r'\s+(?:Careers?|Jobs?)$','',match[2],flags=re.I).strip()
    return None


def company_hint(text,title=''):
    for raw in text.splitlines():
        line=display_line(raw)
        label=re.fullmatch(r'(?:Company|Employer|Hiring organization|Organization):\s*(.{2,120})',line,re.I)
        if label:return label[1].strip(),{'kind':'posting','quote':raw.strip()}
    # A printed page title often contains the employer even with a generic filename.
    for raw in text.splitlines()[:45]:
        line=re.sub(r'^\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}\s*[AP]M\s*','',raw.strip(),flags=re.I)
        split=career_title(line)
        if split:return split[1],{'kind':'posting','quote':raw.strip()}
    split=career_title(title)
    if split:return split[1],{'kind':'title hint','quote':title}
    for raw in text.splitlines():
        line=display_line(raw)
        match=re.match(r'^([A-Z][A-Za-z0-9 &.,’\'-]{1,100}?)\s+(?:is|are)\s+(?:an? equal opportunity employer|committed to being|located\b|hiring\b|seeking\b)\b',line)
        if match and match[1].casefold() not in ('we','our client','the company','this company','the role','this role','the position','this position','our office','our headquarters'):return match[1].strip(),{'kind':'posting','quote':raw.strip()}
    for raw in text.splitlines()[:35]:
        line=display_line(raw)
        if 2<=len(line)<70 and line.casefold() in title.casefold() and not re.search(r'\b(?:analyst|engineer(?:ing)?|internship|intern|manager|specialist|technician|junior|senior|careers?|jobs?)\b',line,re.I) and not re.search(r'\b(?:remote|hybrid|on.site|united states|usa|full.time|part.time)\b|,\s*[A-Z]{2,3}$',line,re.I) and not CITY.fullmatch(line) and not heading(line) and not NOISE.fullmatch(line):
            return line,{'kind':'posting','quote':raw.strip()}
    return '',None


def document_identity(filename,text):
    stem=re.sub(r'\.[^.]+$','',filename)
    title=re.sub(r'^Job Application for\s+','',stem,flags=re.I).strip()
    title=re.sub(r'\s+(?:[-–—]|\|)\s*Careers?$','',title,flags=re.I).strip()
    split=career_title(title)
    sources={}
    if split:
        title,company=split;sources['company']={'kind':'filename hint','quote':filename}
    else:
        company,origin=company_hint(text,title)
        if origin:sources['company']=origin
        # A plain dash/pipe is ambiguous. Split it only when the employer is
        # independently present in the extracted posting, never from a location.
        pieces=re.split(r'\s+[-–—]\s+|\s*\|\s*',title)
        if company and len(pieces)>1 and pieces[-1].casefold()==company.casefold():title=' - '.join(pieces[:-1])
        if title.casefold() in ('job','posting','job posting','job description','document'):
            for line in text.splitlines()[:45]:
                printed=re.sub(r'^\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}\s*[AP]M\s*','',line.strip(),flags=re.I)
                parsed=career_title(printed)
                if parsed:title=parsed[0];sources['title']={'kind':'posting','quote':line.strip()};break
    return {'title':title.split('|')[0].strip()[:250] or 'Job posting','company':company[:250],'identity_sources':sources}


def compact(value): return re.sub(r'\s+',' ',value).strip(' \t•●▪◦*-–—')

def heading(line):
 value=re.sub(r'\s*\(continued\)\s*','',compact(display_line(line)),flags=re.I).rstrip(':').strip().lower()
 if len(value)>200:return None
 for kind,patterns in HEADINGS.items():
  if any(re.fullmatch(pattern,value,re.I) for pattern in patterns):return kind
 return None


def footer_noise(line):
    navigation=re.fullmatch(r"[A-Z0-9.-]+\.[A-Z]{2,}\s+ABOUT .+?\s+CONTACT",line)
    contact=('|' in line and re.match(r'^\d+\s+\S+',line) and re.search(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b',line)
             and re.search(r'\b\d{3}[. -]\d{3}[. -]\d{4}\b',line))
    return bool(navigation or contact)


def print_noise(line):
    return bool(re.match(r'^\d{1,2}/\d{1,2}/\d{2,4},',line) or re.match(r'^Page \d+ of \d+',line,re.I) or NOISE.fullmatch(line) or re.match(r'^On this page:',line,re.I) or footer_noise(line))


def paragraphs(text):
 # Keep source spans, including any intervening print header, while building a
 # separate display from content lines. A sentence can cross a physical page.
 lines=[];offset=0
 for raw in text.splitlines(keepends=True):
  body=raw.rstrip('\r\n');lines.append((body,offset,offset+len(body)));offset+=len(raw)
 result=[];group='intro';pending=[];explicit=False;in_form=False;page_gap=False
 def flush():
  if pending:
   source=text[pending[0][1]:pending[-1][2]].strip()
   value=compact('\n'.join(display_line(row[0]) for row in pending))
   prefix=re.match(r'^([^:]{2,65}):\s*(\S.*)$',value)
   if prefix and heading(prefix[1])==group:value=prefix[2]
   if value:result.append({'text':value,'quote':source,'group':group,'explicit':explicit})
   pending.clear()
 for index,row in enumerate(lines):
  raw,start,end=row;line=display_line(raw)
  if in_form:continue
  if re.match(r'^Apply for this job\s*$',line,re.I):flush();in_form=True;continue
  if not line:
   # Ignore the blank margin around a printed page header only when the
   # preceding sentence is unfinished. Ordinary paragraph breaks stay intact.
   unfinished=bool(pending and not re.search(r'[.!?:]$',display_line(pending[-1][0])))
   next_line=next((display_line(v[0]) for v in lines[index+1:] if v[0].strip()),'')
   if unfinished and (page_gap or print_noise(next_line)):continue
   flush();page_gap=False;continue
  if footer_noise(line) or re.fullmatch(r'(?:Keep looking\s*Apply Now|Apply Now\s*Keep looking)',line,re.I):
   flush();page_gap=False;continue
  if print_noise(line):
   page_gap=True;continue
  if line in ('Apply','-'):flush();page_gap=False;continue
  section=heading(line)
  # A wrapped phrase such as 'without / visa sponsorship' is content, even
  # when the continuation happens to look like a section heading.
  if section and pending and re.search(r'\b(?:without|with|and|or|in|of|to|for)\s*$',display_line(pending[-1][0]),re.I):section=None
  if section:
   flush();group=section;explicit=True;page_gap=False;continue
  inline=re.match(r'^([^:]{2,65}):\s*(\S.*)$',line)
  if inline and heading(inline[1]):
   flush();group=heading(inline[1]);explicit=True;pending.append(row);page_gap=False;continue
  if re.match(r'^(?:As required by local law|The (?:base )?pay range for)',line,re.I):flush();group='pay';explicit=True
  marked=bool(re.match(r'^\s*(?:[•●▪◦*]|[-–—]\s|\d+[.)]\s)',line))
  if pending:
   previous=display_line(pending[-1][0])
   starts_item=START.match(compact(line)) and not(group=='eligibility' and line[:1].islower()) and not previous.endswith(',') and group in ('required','preferred','responsibilities','other','eligibility')
   if marked or starts_item or re.search(r'[.!?:]$',previous):flush()
  pending.append(row);page_gap=False
 flush()
 return result


def organize(data):
 text=data.get('description','');parts=paragraphs(text)
 fact_parts=[{'text':display_line(line) if p['group']=='intro' else p['text'],'quote':line,'group':p['group']} for p in parts for line in (p['quote'].splitlines() if p['group']=='intro' else [p['quote']]) if compact(line) and not print_noise(display_line(line))]
 lines=[compact(l) for l in text.splitlines() if compact(l)]
 facts={k:{'value':'Not stated','sources':[]} for k in ('location','work_arrangement','pay','schedule','dates','deadline')}
 def set_fact(key,value,quote,append=False):
  if not value:return
  target=facts[key]
  if target['value']=='Not stated':target['value']=value
  elif append and value.casefold() not in target['value'].casefold():target['value']+=' · '+value
  if quote not in target['sources']:target['sources'].append(quote)
 # Prefer explicit location sections and labelled metadata over incidental company addresses.
 prioritized=sorted(fact_parts,key=lambda p:0 if p['group']=='location' else 1 if re.search(r'\b(?:based in|based out of|location:|located in)\b',p['text'],re.I) else 2)
 for p in prioritized:
  if p['group']=='ignore':continue
  value=p['text'];matches=list(CITY.finditer(value))
  labelled=re.fullmatch(r'(?:(?:work|job|office|primary) )?location:\s*(.{2,120})',value,re.I)
  if p['group']=='location' and labelled and '\n' not in p['quote'] and not re.search(r'\b(?:schedule|hours|days per week)\b',value,re.I):
   set_fact('location',labelled[1],p['quote']);break
  if matches and (p['group']=='location' or re.search(r'\b(?:based|location|located|relocation|relocate|hybrid|onsite|internship|remote)\b',value,re.I)):
   for m in matches:
    city=m[1]
    city=re.sub(r'^(?:Hybrid or onsite based in |Hybrid or onsite |Based in |Office in |Home Office in |in |in the )','',city,flags=re.I)
    set_fact('location',city+', '+m[2],p['quote'],append=True)
   if facts['location']['value']!='Not stated':break
 if facts['location']['value']=='Not stated':
  for line in lines[:30]:
   match=CITY.fullmatch(line)
   if match:set_fact('location',match[0],line);break
   match=re.match(r'^State/Province:\s*(.+)',line,re.I)
   if match:set_fact('location',match[1],line);break
 if facts['location']['value']=='Not stated':
  for p in fact_parts:
   if p['group']=='location' and len(p['text'])<=160 and not re.search(r'\b(?:schedule|hours|days per week)\b',p['text'],re.I):
    set_fact('location',re.sub(r'^(?:(?:work|job|office|primary) )?location:\s*','',p['text'],flags=re.I),p['quote']);break
 if facts['location']['value']=='Not stated' and data.get('location'):set_fact('location',data['location'],str(data['location']))
 arrangements=[];arrangement_sources=[]
 for p in fact_parts:
  value=p['text']
  if not(p['group'] in ('location','logistics','intro') or re.search(r'\b(?:this role|this position|work (?:arrangement|model)|work (?:is |will be )?(?:fully |primarily )?(?:remote|hybrid|onsite|on.site|in person))\b',value,re.I)):continue
  found=[]
  if re.search(r'\bhybrid\b',value,re.I) and not re.search(r'\b(?:not|no) (?:a )?hybrid\b',value,re.I):found.append('Hybrid')
  if re.search(r'\bremote\b',value,re.I) and not re.search(r'\b(?:(?:not|no) (?:a |an |fully )?remote|remote work (?:is )?(?:not|unavailable)|remote (?:access|desktop|sensing|troubleshooting))\b',value,re.I):found.append('Remote')
  if re.search(r'\b(?:on[- ]?site|in[- ]person)\b',value,re.I) and not re.search(r'\b(?:not|no) (?:an? )?(?:on[- ]?site|in[- ]person)\b',value,re.I):found.append('On-site')
  if found:
   arrangements.extend(found);arrangement_sources.append(p['quote'])
 arrangements=list(dict.fromkeys(arrangements))
 if arrangements:
  set_fact('work_arrangement',' / '.join(arrangements),arrangement_sources[0]);facts['work_arrangement']['sources']=list(dict.fromkeys(arrangement_sources))
 elif data.get('workplace') in ('onsite','hybrid','remote'):
  set_fact('work_arrangement',{'onsite':'On-site','hybrid':'Hybrid','remote':'Remote'}[data['workplace']],data['workplace'])
 # Preserve quoted pay periods/currencies rather than inventing an annual conversion.
 money=re.compile(r'(?:(?:US|USD|EUR|GBP)\s*)?[$€£]\s*\d[\d,.]*(?:\s*[kK])?(?:\s*(?:[-–—]|to)\s*(?:[$€£]\s*)?\d[\d,.]*(?:\s*[kK])?)?(?:\s*(?:/\s*(?:hr|hour|year|yr|annum)|per\s+(?:hour|year|annum)|(?:an?\s+)?(?:hourly|annually)))?',re.I)
 for p in sorted(fact_parts,key=lambda p:0 if p['group']=='pay' else 1 if p['group']=='intro' else 2):
  value=p['text']
  if p['group']=='ignore' or not(p['group'] in ('pay','intro') or re.search(r'\b(?:salary|base pay|pay range|compensation)\b',value,re.I)):continue
  if re.search(r'\b(?:bonus|referral|sign.on)\b',value,re.I) and not re.search(r'\b(?:salary|base pay|pay range|compensation range)\b',value,re.I):continue
  pay=money.search(value)
  if pay:
   amount=pay[0].strip()
   if not re.search(r'/|per |hourly|annually',amount,re.I):
    period=re.search(r'\b(?:per (?:hour|year|annum)|annually|hourly|annual salary)\b',value,re.I)
    if period:amount+=' '+period[0]
   set_fact('pay',amount,p['quote']);break
 schedules=[];dates=[];schedule_sources=[];date_sources=[]
 for p in fact_parts:
  value=p['text']
  if p['group']=='ignore':continue
  # Avoid turning work-authorization "full-time basis" into job schedule metadata.
  if p['group'] in ('intro','location','logistics','program','summary') and not re.search(r'work authori[sz]ation|authorized to work',value,re.I):
   for pattern in (r'\bfull[- ]time\b',r'\bpart[- ]time\b',r'\b\d+(?:\s*[-–]\s*\d+)?\s*hours?\s*(?:per|a|/)\s*week\b',r'\b(?:work\s+)?(?:on[- ]?site|in[- ]person)\s+\d+\s+days?\s+per\s+week\b',r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*(?:through|to|[-–])\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b'):
    for m in re.finditer(pattern,value,re.I):schedules.append(re.sub(r'^(?:work\s+)?on[- ]?site', 'On-site',m[0],flags=re.I));schedule_sources.append(p['quote'])
  for pattern in (r'\b(?:summer|spring|fall|autumn|winter)(?:\s+of)?\s+20\d{2}\b',r'\b\d+[- ]week(?:s)?\b'):
   if p['group'] in ('program','summary','intro','location') or re.search(r'\b(?:internship|program|start|end|duration)\b',value,re.I):
    for m in re.finditer(pattern,value,re.I):dates.append(m[0]);date_sources.append(p['quote'])
  if re.search(r'\b(?:start date|end date|starts? on|ends? on|employment dates|program dates|duration):?\s*',value,re.I):
   label=re.search(r'\b(?:start date|end date|starts? on|ends? on|employment dates|program dates|duration):?\s*',value,re.I)
   # Keep the explicitly labelled date statement rather than guessing a date from a year.
   dates.append(re.sub(r'^duration:\s*','',value[label.start():],flags=re.I));date_sources.append(p['quote'])
  if re.search(r'\b(?:accepting applications|applications(?: accepted)?) until filled\b',value,re.I):set_fact('deadline','Until filled',p['quote'])
  deadline=re.search(r'\b(?:apply by|application deadline|closing date|applications close)\s*:?\s*(.+)',value,re.I)
  if deadline:
   deadline_value=re.split(r'\b(?:SaveShare|Save Share|Apply externally)\b',deadline[1])[0].strip()
   set_fact('deadline',deadline_value,p['quote'])
 if schedules:
  facts['schedule']={'value':' · '.join(dict.fromkeys(schedules)),'sources':list(dict.fromkeys(schedule_sources))}
 if dates:
  dates=[re.sub(r'(\d+)[- ]weeks?\b',r'\1 weeks',re.sub(r'\b(summer|spring|fall|autumn|winter) of ',r'\1 ',v,flags=re.I),flags=re.I) for v in dates]
  dates=[v[0].upper()+v[1:] for v in dates]
  dates=sorted(dict.fromkeys(dates),key=lambda v:1 if re.fullmatch(r'\d+ weeks',v) else 0)
  facts['dates']={'value':' · '.join(dates),'sources':list(dict.fromkeys(date_sources))}
 sections={k:[] for k in ('required','preferred','responsibilities','eligibility','other')};seen=set();summary=[];logistics_notes=[]
 def add(kind,value,quote):
  value=compact(value);key=re.sub(r'\W+',' ',value).strip().casefold()
  if re.search(r'\b(?:currently enrolled|rising[ -](?:senior|junior)|enrollment|graduat(?:e|ion) (?:by|between|before|after)|pursuing (?:a |an )?(?:degree|bachelor|master)|working towards? (?:a |an )?(?:degree|bachelor|master)|graduation date)',value,re.I) and kind in ('required','preferred','other'):kind='eligibility'
  if value and key not in seen:
   sections[kind].append({'id':hashlib.sha256((kind+'|'+value.casefold()).encode()).hexdigest()[:20],'text':value,'source':quote,'classification':kind});seen.add(key)
 for p in parts:
  kind=p['group'];value=p['text']
  if kind=='summary' and len(value)>60 and not re.search(r'\b(?:cookie|privacy policy|apply now)\b',value,re.I):summary.append(value)
  if kind not in sections:
   if kind=='intro' and re.search(r'\b(?:must have|must be|is required|are required|minimum qualifications|preferred)\b',value,re.I):add('preferred' if re.search(r'\bpreferred\b',value,re.I) else 'required',value,p['quote'])
   continue
  if kind in ('required','preferred','other') and re.match(r'^(?:This is more than a job|Whether you aspire|As a company|We believe|We offer|Our company)\b',value,re.I):continue
  if kind in ('required','preferred','other'):
   # A mixed sentence can contain required enrollment and a preferred major.
   mixed=re.match(r'^(.*?)[,;]\s*((?:in\s+)?an?\s+[^,;]+\b(?:major|degree|field)[^,;]*\bpreferred[^,;]*)$',value,re.I)
   if mixed and kind=='required':
    add('required',mixed[1],p['quote']);preferred_text=re.sub(r'^in\s+','',mixed[2],flags=re.I);preferred_text=re.sub(r'\s+preferred\b','',preferred_text,flags=re.I);add('preferred',preferred_text[0].upper()+preferred_text[1:],p['quote']);continue
   # Relocation belongs to job logistics, never the applicant qualification score.
   if re.match(r'^(?:relocation to|(?:must |required to )?relocate to)\b',value,re.I):
    logistics_notes.append(value);continue
   clauses=re.split(r';\s*(?=[A-Za-z])',value) if re.search(r'\brequired\b',value,re.I) and re.search(r'\bpreferred\b',value,re.I) else [value]
   for clause in clauses:
    preferred=bool(re.search(r'\b(?:preferred|nice.to.have|a plus|a bonus|desirable)\b',clause,re.I))
    target='preferred' if preferred else kind
    if re.search(r'\b(?:must|required|mandatory|minimum)\b',clause,re.I) and not preferred:target='required'
    if re.search(r'\b(?:authorized to work|work authori[sz]ation|sponsorship|citizen(?:ship)?)\b',clause,re.I) or re.match(r'^(?:(?:COVID[- ]?19\s+)?vaccination\b|(?:proof of|must provide|must have|required).*?\bvaccination\b)',clause,re.I):target='eligibility'
    add(target,clause,p['quote'])
  else:add(kind,value,p['quote'])
 # Facts are allowed to be unknown. Do not infer location from company headquarters.
 company=data.get('company','');identity_sources={}
 if not company:
  company,origin=company_hint(text,data.get('title',''))
  if origin:identity_sources['company']=origin
 return {'parser_version':VERSION,'text_hash':hashlib.sha256(text.encode()).hexdigest(),'title':data.get('title','Job posting'),'company':company,'identity_sources':identity_sources,'facts':facts,'summary':summary[:1],'sections':sections,'notes':(['The posting mentions more than one work arrangement. Check its onsite schedule.'] if len(arrangements)>1 else [])+list(dict.fromkeys(logistics_notes)),'original_text':text}


def criteria(data):
    """The same catalog drives overview, AI assessment, and score denominators."""
    overview=organize(data)
    return [{**row,'kind':'eligibility' if group=='eligibility' else 'qualification',
             'importance':'preferred' if group=='preferred' else 'required',
             'classification_reason':'Employment eligibility or work-authorization rule; excluded from qualifications scoring.' if group=='eligibility' else 'Explicit '+group+' qualification in the posting.'}
            for group in ('required','preferred','eligibility') for row in overview['sections'][group]]
