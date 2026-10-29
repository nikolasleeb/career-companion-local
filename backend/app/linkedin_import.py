"""Local parser for LinkedIn exports with separate main/sidebar text streams."""
import hashlib,re
from . import resume_parser
from .models import ExperienceItem
from .import_values import repair_wrapped_links
MAIN='[[LinkedIn main]]';SIDE='[[LinkedIn sidebar]]'
DURATION=re.compile(r'^(?:\d+\s+(?:years?|months?)\s*)+$',re.I)
DATE=re.compile(r'^(?:[A-Za-z]+\s+)?(?:19|20)\d{2}\s*[-–—]\s*(?:Present|(?:[A-Za-z]+\s+)?(?:19|20)\d{2})(?:\s*\([^)]*\))?$',re.I)

def location(value):
    return resume_parser.location(value) or bool(re.fullmatch(r"[^,]+,\s*[^,]+,\s*(?:United States|Canada|United Kingdom|Australia)",value,re.I))

def parse(text):
    clean=repair_wrapped_links(re.sub(r'(?im)^\s*Page\s+\d+\s+(?:of|/)\s*\d+\s*$','',text)).replace('\xa0',' ')
    if MAIN not in clean:
        # Old one-column/manual sources remain supported. Isolate a sidebar that
        # ends at the recognizable name/headline/location block when possible.
        lines=[x.strip() for x in clean.splitlines() if x.strip()]
        exp=next((i for i,x in enumerate(lines) if resume_parser.heading(x)=='employment'),None)
        if exp is not None and 'Contact' in lines[:exp]:
            location_index=next((i for i in range(exp-1,-1,-1) if location(lines[i])),None)
            if location_index is not None and location_index>=2:
                header=location_index-2;clean=MAIN+'\n'+'\n'.join(lines[header:])+ '\n'+SIDE+'\n'+'\n'.join(lines[:header])
        if MAIN not in clean and any(DATE.fullmatch(l) for l in lines):clean=MAIN+'\n'+clean
        if MAIN not in clean:
            clean=re.sub(r'(?im)^\s*Top Skills\s*$','Skills',clean)
            clean=re.sub(r'(?im)^\s*Contact\s*$','',clean)
            result=resume_parser.parse(clean)
            return result
    main,_,sidebar=clean.replace(MAIN,'',1).partition(SIDE)
    lines=[x.strip() for x in main.splitlines() if x.strip()]
    groups=[];current={'kind':'header','lines':[]}
    for line in lines:
        kind=resume_parser.heading(line)
        if kind:
            if current['lines']:groups.append(current)
            current={'kind':kind,'lines':[]}
        else:current['lines'].append(line)
    if current['lines']:groups.append(current)
    header=next((g['lines'] for g in groups if g['kind']=='header'),[])
    contact=[];sidegroups=[];active={'kind':'contact','lines':[]}
    for line in [x.strip() for x in sidebar.splitlines() if x.strip()]:
        kind='contact' if line=='Contact' else 'skills' if line=='Top Skills' else resume_parser.heading(line)
        if kind:
            if active['lines']:sidegroups.append(active)
            active={'kind':kind,'lines':[]}
        else:active['lines'].append(line)
    if active['lines']:sidegroups.append(active)
    for g in sidegroups:
        if g['kind']=='contact':contact.extend(g['lines'])
    result=resume_parser.parse('\n'.join(header+contact))
    result['entries']=[]
    def uncertain(raw,reason):
        if raw:result['unmapped'].append({'text':raw,'reason':reason})
    def add(category,title,raw,**fields):
        try:data=ExperienceItem.model_validate({'category':category,'title':title,'confirmed':False,**fields}).model_dump()
        except ValueError:uncertain(raw,'Needs review: some fields could not be safely assigned.');return
        identity=hashlib.sha256(('linkedin\n'+category+'\n'+raw).encode()).hexdigest()[:24]
        if not any(e['id']==identity for e in result['entries']):result['entries'].append({'id':identity,'data':data,'source_text':raw,'warnings':[]})
    for g in groups:
        body=g['lines'];kind=g['kind']
        if kind=='header':continue
        if kind=='employment':
            dates=[i for i,line in enumerate(body) if DATE.fullmatch(line)]
            heads=[];employer=''
            for n,i in enumerate(dates):
                # Explicit LinkedIn headings: employer / [duration] / role / date.
                title=body[i-1] if i else ''
                start=i-1
                if i>=2 and DURATION.fullmatch(body[i-2]):
                    if i>=3:employer=body[i-3];start=i-3
                elif i>=2 and resume_parser.short_title(body[i-2]) and not DATE.fullmatch(body[i-2]) and not location(body[i-2]) and not DURATION.fullmatch(body[i-2]) and not body[i-2].startswith(('-', '•')):
                    employer=body[i-2];start=i-2
                if not title or not employer or DURATION.fullmatch(title) or location(employer):
                    uncertain('\n'.join(body[max(0,i-2):i+1]),'Needs review: employer and role could not be separated.');heads.append((i,start,None));continue
                heads.append((i,start,(title,employer)))
            for n,(i,start,identity) in enumerate(heads):
                end=heads[n+1][1] if n+1<len(heads) else len(body)
                if not identity:continue
                title,employer=identity;details=body[i+1:end];loc=''
                if details and location(details[0]):loc=details.pop(0)
                datestr=re.sub(r'\s*\([^)]*\)\s*$','',body[i]);raw='\n'.join(body[start:end])
                add('employment',title,raw,organization=employer,location=loc,description='\n'.join(details),**resume_parser.date_fields(datestr))
            if not dates:uncertain('\n'.join(body),'Needs review: no explicit employment date ranges were found.')
        elif kind=='education':
            starts=[i for i,l in enumerate(body) if resume_parser.SCHOOL.search(l) and not resume_parser.DEGREE.search(l) and not resume_parser.DATE_RANGE.search(l)]
            for n,i in enumerate(starts):
                block=body[i:(starts[n+1] if n+1<len(starts) else len(body))];raw='\n'.join(block)
                if len(block)<2:uncertain(raw,'Needs review: qualification missing.');continue
                date_lines=[l for l in block[1:] if DATE.fullmatch(l)]
                qualification=' '.join(l for l in block[1:] if l not in date_lines);qualification,date=(qualification.split('·',1)+[''])[:2] if '·' in qualification else (qualification,'')
                # LinkedIn commonly prints generic degree names rather than MS/MA.
                generic=re.match(r"^((?:Master|Bachelor|Associate)(?:'s|’s)? degree)\s*,?\s*(.*)$",qualification,re.I)
                if generic:
                    degree,major=generic.groups()
                else:
                    match=resume_parser.DEGREE.search(qualification)
                    if not match:uncertain(raw,'Needs review: qualification could not be identified.');continue
                    degree=match.group();major=qualification[match.end():].strip(' ,-')
                    major=re.sub(r'^(?:-?\s*(?:BS|BA|MS|MA)\s*,\s*|in\s+)','',major,flags=re.I)
                date=date or (date_lines[0] if date_lines else '')
                fields=resume_parser.date_fields(date.strip(' ()')) if date else {}
                add('education',qualification.strip(),raw,organization=body[i],degree=degree,major=major,**fields)
            if not starts:uncertain('\n'.join(body),'Needs review: education headings could not be separated.')
        else:
            delegated=resume_parser.parse(kind.upper()+'\n'+'\n'.join(body));result['entries'].extend(delegated['entries']);result['unmapped'].extend(delegated['unmapped'])
    for g in sidegroups:
        if g['kind']=='skills':
            skills=[l for l in g['lines'] if l and not DURATION.fullmatch(l)]
            if skills:add('skills','Skills','\n'.join(skills),tools='; '.join(skills),skill_items=[{'name':l} for l in skills])
        elif g['kind']=='certifications':
            names=[]
            for line in g['lines']:
                if names and re.fullmatch(r'(?:Practitioner|Professional|Associate|Specialist|Fundamentals)(?:\s+\w+)?',line,re.I) and not re.search(r'Practitioner|Professional|Associate|Specialist|Fundamentals',names[-1],re.I):names[-1]+=' '+line
                else:names.append(line)
            for name in names:
                if location(name) or len(name.split())<2:uncertain(name,'Needs review: credential name is incomplete.');continue
                add('skills','Certifications',name,tools=name,certification_items=[{'name':name}])
        elif g['kind']!='contact':uncertain('\n'.join(g['lines']),'Needs review: sidebar section retained for inspection.')
    result['warnings']=['LinkedIn columns were read separately. Review proposed information before saving.']
    if len(result['entries'])>100:
        for e in result['entries'][100:]:uncertain(e['source_text'],'Needs review: additional entry beyond the review limit.')
        result['entries']=result['entries'][:100]
    return result
