"""Conservative local resume parsing. Source text is data, never instructions.

No model calls, URL requests, date completion, or inferred credentials. Every
proposal retains its source passage; uncertain text stays visible for review.
"""
import hashlib
import re
from .models import ExperienceItem, SettingsUpdate

VERSION='local-v2-github'
SECTIONS={
 'education':{'education','academic background','academic qualifications','education and training'},
 'employment':{'experience','work experience','professional experience','employment','employment history','work history','professional background'},
 'project':{'projects','academic projects','selected projects','personal projects','technical projects','research projects','project experience'},
 'skills':{'skills','technical skills','core skills','core competencies','technical competencies','technologies'},
 'volunteering':{'volunteering','volunteer experience','volunteer work','community involvement','community service','leadership and service'},
 'coursework':{'coursework','relevant coursework','relevant classes'},
 'certifications':{'certifications','certificates','licenses and certifications','certifications and licenses'},
 'summary':{'summary','professional summary','profile','objective','career objective'},
 'honors':{'honors','awards','honors and awards','awards and honors'},
}
DEGREE=re.compile(r'\b(Master(?:s|\u2019s|\'s)? of (?:Science|Arts|Business Administration)|Bachelor(?:s|\u2019s|\'s)? of (?:Science|Arts|Business Administration)|Associate(?: of (?:Science|Arts|Applied Science))?|Ph\.?D\.?|Doctor of [A-Za-z ]+|M\.?S\.?|M\.?A\.?|MSc|BSc|B\.?S\.?|B\.?A\.?|MBA)\b',re.I)
YEAR=re.compile(r'\b(?:19|20)\d{2}\b')
DATE_RANGE=re.compile(r'(?:(?:[A-Za-z]{3,9}\s+)?(?:19|20)\d{2}|[A-Za-z]{3,9})\s*[–—-]\s*(?:Present|Current|Now|(?:[A-Za-z]{3,9}\s+)?(?:19|20)\d{2})\b',re.I)
ACTION=re.compile(r'^(?:I\b|Designed|Built|Developed|Created|Managed|Used|Led|Owned|Collaborated|Supported|Assisted|Held|Provided?|Continue|Refine|Plan|Prepare|Conducted|Cleaned|Leveraged|Engineered|Implemented|Analyzed|Worked|Responsible|Collected|Trained|Demonstrated|Independently|Identified|Adapted|Wrote|Configured|Performed|Maintained)\b',re.I)
BULLET=re.compile(r'^\s*(?:[•●▪◦*\u25cf]|[-–]\s|\d+[.)]\s)\s*')
SCHOOL=re.compile(r'\b(?:university|college|institute|polytechnic|school|tech)\b',re.I)
URL=re.compile(r'(?:https?://|www\.)[^\s<>|)]+',re.I)

def heading(text):
    key=re.sub(r'\s+',' ',text.strip(' :–—-\t')).casefold().replace('&','and')
    return next((kind for kind,names in SECTIONS.items() if key in names),None)

def plain(line): return BULLET.sub('',line).strip()

def location(value):
    return bool(re.fullmatch(r'[A-Za-z .\u2019\'-]+,\s*(?:[A-Z]{2}|[A-Za-z .-]+)(?:\s*&\s*[A-Za-z .-]+,\s*[A-Z]{2})?',value)) and not DEGREE.search(value)

def degree_line(line): return bool(DEGREE.search(line)) and len(line)<350 and not ACTION.search(plain(line))

def short_title(line):
    value=plain(line)
    return bool(value) and not re.match(r'^(?:Tools|Technologies|Role|Contribution|Team|Dates?|Link)\s*:',value,re.I) and not BULLET.match(line) and len(value)<=220 and len(value.split())<=27 and not ACTION.search(value) and not value.endswith(('.',':',';')) and not URL.search(value)

def date_fields(text):
    expected=re.search(r'\bExpected(?:\s+graduation)?\s*[:\-]?\s*((?:[A-Za-z]+\s+)?(?:19|20)\d{2})\b',text,re.I)
    found=DATE_RANGE.search(text)
    result={}
    if expected: result['expected_graduation']=expected.group(1)
    if found:
        result['dates']=found.group()
        halves=re.split(r'\s*[–—-]\s*',found.group(),maxsplit=1)
        # Never manufacture a year for abbreviated ranges such as Jun–Aug 2026.
        if YEAR.search(halves[0]): result.update(start_date=halves[0],end_date=halves[1])
    elif expected: result['dates']=expected.group()
    else:
        single=re.search(r'\b(?:[A-Za-z]+\s+)?(?:19|20)\d{2}\b',text)
        if single: result['dates']=single.group();result['end_date']=single.group()
    return result

def fingerprint(data):
    import json
    return hashlib.sha256(json.dumps({k:v for k,v in ExperienceItem.model_validate(data).model_dump().items() if k not in ('confirmed','source_document_id','source_entry_id')},sort_keys=True).encode()).hexdigest()

def parse(text):
    lines=[line.strip() for line in text.replace('\r','').split('\n') if line.strip()]
    groups=[];current={'kind':'header','heading':'','lines':[]}
    for line in lines:
        kind=heading(line)
        if kind:
            if current['lines']: groups.append(current)
            current={'kind':kind,'heading':line,'lines':[]}
        else: current['lines'].append(line)
    if current['lines']: groups.append(current)
    result={'parser_version':VERSION,'text_hash':hashlib.sha256(text.encode()).hexdigest(),'profile':{},'profile_evidence':{},'entries':[],'unmapped':[],'warnings':[]}
    def unmapped(source,reason):
        if source.strip(): result['unmapped'].append({'text':source,'reason':reason})
    def profile(key,value,source):
        if value and key not in result['profile']:
            try: SettingsUpdate.model_validate({key:value})
            except ValueError: return
            result['profile'][key]=value;result['profile_evidence'][key]=source
    def entry(category,title,source,fields=None,warnings=None):
        if not source.strip(): return
        fields=fields or {};warnings=list(warnings or [])
        data={'category':category,'title':title[:200] or category.title(),'confirmed':False,**fields}
        for key,field in ExperienceItem.model_fields.items():
            if isinstance(data.get(key),str):
                limits=[m.max_length for m in field.metadata if hasattr(m,'max_length')]
                if limits and len(data[key])>min(limits):
                    data[key]=data[key][:min(limits)];warnings.append(key.replace('_',' ').title()+' was shortened; the full passage is retained below.')
        try: data=ExperienceItem.model_validate(data).model_dump()
        except ValueError:
            unmapped(source,'Some fields could not be safely parsed. Review this passage manually.');return
        identity=hashlib.sha256((category+'\n'+source).encode()).hexdigest()[:24]
        # Same source block repeated verbatim only needs one proposal.
        if any(e['id']==identity for e in result['entries']): return
        result['entries'].append({'id':identity,'data':data,'source_text':source,'warnings':warnings})

    for group in groups:
        kind=group['kind'];body=group['lines'];source='\n'.join(body)
        if kind=='header':
            if body:
                first=plain(body[0])
                if len(first)<=150 and 1<len(first.split())<7 and not any(c in first for c in '@|0123456789') and not heading(first): profile('name',first,body[0])
            for line in body:
                email=re.search(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',line,re.I)
                if email: profile('email',email.group(),line)
                phone=re.search(r'(?<!\w)(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?:\s*(?:ext\.?|x)\s*\d+)?\b',line,re.I)
                if phone: profile('phone',phone.group().strip(),line)
                for part in re.split(r'\s*\|\s*',line):
                    if location(part):
                        city,state=part.rsplit(',',1);profile('city',city.strip(),line);profile('state',state.strip(),line)
                for match in URL.finditer(line):
                    url=match.group().rstrip('.,;')
                    if url.startswith('www.'): url='https://'+url
                    from urllib.parse import urlparse
                    host=(urlparse(url).hostname or '').lower()
                    key='linkedin' if host in ('linkedin.com','www.linkedin.com') else 'github' if host in ('github.com','www.github.com') else 'website'
                    profile(key,url,line)
            for i,line in enumerate(body):
                if i==0 and result['profile'].get('name')==plain(line): continue
                if any(line==quote for key,quote in result['profile_evidence'].items() if key!='name'): continue
                if i==1 and len(line)<=250 and not any(c in line for c in '@0123456789'):
                    profile('headline',plain(line),line)
                else: unmapped(line,'Header text was not confidently assigned to a field.')
        elif kind in ('skills','certifications'):
            for line in body:
                value=plain(line)
                if kind=='certifications' or (':' in value and re.search(r'certific|licen[cs]e',value.split(':',1)[0],re.I)):
                    detail=value.split(':',1)[1].strip() if ':' in value else value
                    names=[v.strip() for v in re.split(r'[,;•]+',detail) if v.strip()]
                    entry('skills','Certifications',line,{'tools':detail,'certification_items':[{'name':v[:200]} for v in names]},['Review credential names, issuer, and dates. No active status is inferred.'])
                elif ':' in value:
                    title,detail=value.split(':',1)
                    entry('skills',title.strip(),line,{'tools':detail.strip()})
                else: entry('skills',group['heading'],line,{'description':value})
        elif kind in ('employment','volunteering'):
            chunks=[];chunk=[]
            for i,line in enumerate(body):
                next_dated=i+1<len(body) and bool(DATE_RANGE.search(body[i+1])) and len(body[i+1])<220
                starts=(bool(DATE_RANGE.search(line)) and not BULLET.match(line) and not ACTION.search(plain(line)) and (len(line)<220 or '|' in line)) or (short_title(line) and next_dated)
                if starts and chunk:
                    # A title immediately followed by a dated employer line belongs together.
                    if not (len(chunk)<=2 and all(short_title(x) and not DATE_RANGE.search(x) for x in chunk)): chunks.append(chunk);chunk=[]
                chunk.append(line)
            if chunk: chunks.append(chunk)
            for chunk in chunks:
                header=[chunk[0]];offset=1
                if len(chunk)>2 and DATE_RANGE.search(chunk[2]) and short_title(chunk[1]): header.extend(chunk[1:3]);offset=3
                elif len(chunk)>1 and DATE_RANGE.search(chunk[1]) and len(chunk[1])<220 and not ACTION.search(plain(chunk[1])): header.append(chunk[1]);offset=2
                parts=[p.strip() for p in re.split(r'\s*\|\s*',' | '.join(header)) if p.strip()]
                dates=date_fields(' | '.join(header));locs=[p for p in parts if location(p)]
                other=[p for p in parts[1:] if not location(p) and not DATE_RANGE.search(p)]
                warnings=[]
                if not dates: warnings.append('Dates were not confidently identified.')
                if not other: warnings.append('Role and employer were not separately identified; review this heading.')
                entry(kind,parts[0], '\n'.join(chunk),{**dates,'organization':' | '.join(other) or (parts[0] if re.search(r'\b(?:inc|llc|corp|company|centers?)\b',parts[0],re.I) else ''),'location':' | '.join(locs),'description':'\n'.join(plain(l) for l in chunk[offset:])},warnings)
        elif kind=='project':
            chunks=[];chunk=[]
            for line in body:
                if short_title(line) and chunk: chunks.append(chunk);chunk=[]
                chunk.append(line)
            if chunk: chunks.append(chunk)
            for chunk in chunks:
                title=plain(chunk[0]);details=chunk[1:]
                if ':' in title:
                    title,rest=title.split(':',1);details=[rest.strip(),*details]
                contribution=[plain(l) for l in details if re.match(r'^(?:I\b|My contribution\b|Owned\b)',plain(l),re.I)]
                tool_lines=[plain(l).split(':',1)[1].strip() for l in details if re.match(r'^(?:Tools|Technologies)\s*:',plain(l),re.I)]
                description=[plain(l) for l in details if plain(l) not in contribution and not re.match(r'^(?:Tools|Technologies)\s*:',plain(l),re.I)]
                links=[m.group().rstrip('.,;') for l in details for m in URL.finditer(l) if m.group().startswith(('http://','https://'))]
                entry('project',title,'\n'.join(chunk),{'description':'\n'.join(description),'contribution':'\n'.join(contribution),'tools':'; '.join(tool_lines),'project_url':links[0] if links else '', 'project_urls':list(dict.fromkeys(links))[:5]})
        elif kind=='education':
            chunks=[];chunk=[]
            for line in body:
                start=degree_line(line) or (SCHOOL.search(line) and ':' not in line and short_title(line) and ('|' in line or not chunk))
                if start and chunk and any(degree_line(x) for x in chunk[:2]): chunks.append(chunk);chunk=[]
                chunk.append(line)
            if chunk: chunks.append(chunk)
            for chunk in chunks:
                heads=chunk[:1]
                if len(chunk)>1 and (degree_line(chunk[1]) or (not degree_line(chunk[0]) and SCHOOL.search(chunk[1]))): heads.append(chunk[1])
                if len(chunk)>len(heads) and re.fullmatch(r'(?:Expected(?: graduation)?\s+)?(?:[A-Za-z]+\s+)?(?:19|20)\d{2}',plain(chunk[len(heads)]),re.I): heads.append(chunk[len(heads)])
                head=' | '.join(heads);match=DEGREE.search(head)
                if not match:
                    unmapped('\n'.join(chunk),'Education entry needs a school or qualification heading.');continue
                parts=[p.strip() for p in head.split('|')];degree_part=next((p for p in parts if DEGREE.search(p)),head)
                degree=DEGREE.search(degree_part);major=degree_part[degree.end():].strip(' ,–-')
                if major.lower().startswith('in '): major=major[3:]
                school=next((p for p in parts if not DEGREE.search(p) and SCHOOL.search(p)), '')
                fields={'degree':degree.group(),'major':major,'organization':school,**date_fields(head)}
                notes=[];honors=[];courses=[];project=None;projects=[]
                for line in chunk[len(heads):]:
                    value=plain(line)
                    inline=re.match(r'^([^:]{0,190}(?:Analysis|Project|Dashboard|Application|Study)):\s*(.+)$',value,re.I)
                    if inline:
                        if project: projects.append(project)
                        project={'title':inline.group(1),'lines':[line],'description':[inline.group(2)]};continue
                    if re.match(r'^(?:Relevant\s+)?(?:Coursework|Courses|Classes)\s*:',value,re.I): courses.append(value.split(':',1)[1].strip());continue
                    if re.match(r'^(?:Honors|Awards)\s*:',value,re.I): honors.append(value.split(':',1)[1].strip());continue
                    gpa=re.search(r'\bGPA\s*:?\s*(\d(?:\.\d+)?)\s*(?:/\s*(\d(?:\.\d+)?))?',value,re.I)
                    if gpa: fields['gpa']=gpa.group(1);fields['gpa_scale']=gpa.group(2) or '';continue
                    labelled=re.match(r'^(Minor|Concentration)\s*:\s*(.+)$',value,re.I)
                    if labelled: fields[labelled.group(1).lower()]=labelled.group(2);continue
                    if project: project['lines'].append(line);project['description'].append(value)
                    else: notes.append(value)
                if project: projects.append(project)
                fields.update(description='\n'.join(notes),honors='\n'.join(honors),relevant_courses='\n'.join(courses))
                warnings=[] if school else ['Institution was not confidently identified.']
                entry('education',degree_part,'\n'.join(chunk),fields,warnings)
                for project in projects: entry('project',project['title'],'\n'.join(project['lines']),{'organization':school,'description':'\n'.join(project['description'])},['Found inside Education; verify its course or organization.'])
        elif kind=='coursework': entry('coursework',group['heading'],source,{'description':'\n'.join(plain(l) for l in body)})
        else: unmapped(source,'This '+kind+' section is retained for manual review.')
    if len(result['entries'])>100:
        for item in result['entries'][100:]: unmapped(item['source_text'],'Additional entry beyond the 100-entry review limit.')
        result['entries']=result['entries'][:100]
    if not result['entries']: result['warnings'].append('No clear resume sections were found. Use source text to add records manually.')
    result['warnings'].append('Local parsing uses headings and text patterns. Review role titles, dates, grouping, and missing details before importing.')
    return result
