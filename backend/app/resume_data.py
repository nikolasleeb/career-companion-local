"""Build immutable, display-ready resume snapshots from confirmed records.

Old snapshots and generic records remain readable without rewriting stored data.
"""
import re
import hashlib
import unicodedata
from .documents import clean
from .education import subjects


def contact_lines(profile):
    location=', '.join(filter(None,(clean(profile.get(k)) for k in ('city','county','state','country'))))
    primary=' | '.join(filter(None,[clean(profile.get('email')),clean(profile.get('phone')),location]))
    links=' | '.join(filter(None,[clean(profile.get('website')),clean(profile.get('linkedin'))]))
    lines=[value for value in (primary,links) if value]
    legacy=clean(profile.get('contact'))
    if legacy and not profile.get('contact_reviewed') and legacy not in lines:
        lines.append(legacy)
    return lines


def record_dates(data):
    attendance=' – '.join(filter(None,[clean(data.get('start_date')),clean(data.get('end_date'))]))
    graduation=clean(data.get('expected_graduation')) if data.get('category')=='education' else ''
    structured='; '.join(filter(None,[attendance,'Expected graduation '+graduation if graduation else '']))
    return structured or clean(data.get('dates'))


def entry_snapshot(data,source_id,granular=False):
    title=clean(data.get('title'))
    majors=' & '.join(subjects(data,'major'));minors='; '.join(subjects(data,'minor'))
    if data.get('category')=='education' and clean(data.get('degree')):
        title=clean(data['degree'])+(' in '+majors if majors else '')
    details=[clean(data.get('organization')),clean(data.get('location'))]
    if data.get('category')=='employment':
        details.append({'onsite':'On-site','hybrid':'Hybrid','remote':'Remote'}.get(data.get('work_arrangement'),''))
    dates=record_dates(data)
    details.append(dates)
    bullets=[]
    if data.get('category')=='education':
        if not clean(data.get('degree')) and majors: bullets.append('Majors: '+majors)
        if minors:bullets.append(('Minors: ' if len(subjects(data,'minor'))>1 else 'Minor: ')+minors)
        for key,label in [('concentration','Concentration')]:
            if clean(data.get(key)): bullets.append(label+': '+clean(data[key]))
        gpa=clean(data.get('gpa'))
        if gpa: bullets.append('GPA: '+gpa+(' / '+clean(data['gpa_scale']) if clean(data.get('gpa_scale')) else ''))
        for key,label in [('honors','Honors'),('relevant_courses','Relevant classes')]:
            if clean(data.get(key)):
                if granular and key=='relevant_courses':
                    bullets.extend('Relevant class: '+v.strip() for v in re.split(r'[;\n]' if re.search(r'[;\n]',clean(data[key])) else r',',clean(data[key])) if v.strip())
                else: bullets.append(label+': '+clean(data[key]))
    from . import certifications
    for field in ('description','contribution','accomplishments'):
        if field=='description' and certifications.is_group(data) and not data.get('certification_items') and not data.get('tools') and not data.get('skill_items'): continue
        bullets.extend(clean(line.strip(' •-')) for line in str(data.get(field,'')).splitlines() if clean(line.strip(' •-')))
    from . import certifications
    if certifications.is_group(data):
        bullets.extend(certifications.text(v) for v in certifications.rows(data))
    elif data.get('category')=='skills' and data.get('skill_items'):
        values=[clean(v['name'])+(' ('+v['level']+', self-rated)' if v.get('level','unknown')!='unknown' else '') for v in data['skill_items'] if clean(v.get('name'))]
        bullets.extend(values if granular else ['Skills: '+', '.join(values)])
    elif clean(data.get('tools')):
        if granular and data.get('category')=='skills': bullets.extend(v.strip() for v in re.split(r'[;,\n]',clean(data['tools'])) if v.strip())
        else: bullets.append('Tools: '+clean(data['tools']))
    if data.get('category')=='project':
        from .models import project_links
        bullets.extend('Project: '+clean(url) for url in project_links(data))
    bullets=list(dict.fromkeys(bullets))
    items=[]
    for value in bullets:
        field='description'
        if data.get('category')=='skills':
            context=[clean(line.strip(' •-')) for key in ('description','contribution','accomplishments') for line in str(data.get(key,'')).splitlines()]
            field='certification' if certifications.is_group(data) else 'skill_context' if value in context else 'skill'
        elif value.startswith(('Relevant class:','Relevant classes:')):field='course'
        elif value.startswith('GPA:'):field='gpa'
        elif value.startswith('Honors:'):field='honors'
        elif value.startswith(('Major:','Minor:','Concentration:')):field='education_detail'
        elif value.startswith('Tools:'):field='tools'
        elif value.startswith('Project:'):field='url'
        elif data.get('category')=='education':field='education_note'
        elif value in str(data.get('contribution','')):field='contribution'
        elif value in str(data.get('accomplishments','')):field='accomplishment'
        item_id=hashlib.sha256((str(data.get('title'))+'|'+str(data.get('organization'))+'|'+field+'|'+value).encode()).hexdigest()[:24]
        items.append({'item_id':item_id,'field':field,'original':value,'text':value})
    return {**data,'source_id':source_id,'title':title,'dates':dates,'details':' | '.join(filter(None,details)),
            'organization':clean(data.get('organization')),'bullets':bullets,'content_items':items}


def _filename_part(value):
    value=unicodedata.normalize('NFC',clean(value))
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f,\s–—]+','-',value)
    return re.sub(r'-+','-',value).strip(' .-')


def _document_role(title,company):
    """Strip known posting metadata, never an arbitrary role specialization."""
    role=clean(title)
    if company:
        role=re.sub(r'^'+re.escape(company)+r'(?:\s*[-–—|:]\s*|\s+)','',role,flags=re.I).strip() or role
    metadata=r'(?:United States|United Kingdom|USA|U\.S\.?A?\.?|Canada|Australia)(?:\b|$)|(?:remote|hybrid|on[- ]site)(?:\s*\([^)]*\))?$|(?:Ph\.?D\.?|Masters?|Bachelor\S*|Graduate|Undergraduate)(?:\s+or\s+\w+)*\s+(?:Student|Candidates?)\b|(?:Job|Requisition|Req)\s*(?:ID|Number|#)\b|(?:University|Campus|Talent)\s+(?:Recruiting|Acquisition)\b'
    for boundary in re.finditer(r'\s+[-–—]\s+|\s*\|\s*|\s*,\s*|[-–—]{2,}',role):
        tail=role[boundary.end():].strip()
        if re.match(metadata,tail,re.I) or company and re.match(re.escape(company)+r'\s+(?:Uni\b|University\b|Talent\b|Recruiting\b)',tail,re.I):
            return role[:boundary.start()].strip() or role
    return role


def resume_title(posting,fallback='Resume',name=''):
    """Safe short label for display and downloads; source snapshots stay intact."""
    posting=posting or {}
    company=clean(posting.get('company'))
    role=_document_role(posting.get('title'),company)
    core='-'.join(filter(None,(_filename_part(company),_filename_part(role)))) if company or role else _filename_part(fallback)
    core=re.sub(r'(?:-?Resume)$','',core,flags=re.I).strip(' .-')
    person=_filename_part(name)
    if person and core.casefold()!=person.casefold() and not core.casefold().startswith(person.casefold()+'-'):
        core='-'.join(filter(None,(person,core)))
    # Reserve the suffix first, then shorten on a word boundary where possible.
    budget=180-len('-Resume'.encode())
    if len(core.encode('utf-8'))>budget:
        shortened=core.encode('utf-8')[:budget].decode('utf-8','ignore')
        core=shortened.rsplit('-',1)[0] if '-' in shortened else shortened
    return core.rstrip(' .-')+'-Resume' if core else 'Resume'


def resume_filename(snapshot,format):
    title=resume_title(snapshot.get('posting_snapshot'),snapshot.get('title') or 'Resume',snapshot.get('name') or '')
    return title+'.'+format
