"""Compact employer-facing skills; source items and Profile metadata remain intact."""
import copy
import re
from . import certifications

RATING=re.compile(r'\s*\((?:beginner|intermediate|advanced|expert),\s*self-rated\)',re.I)


def certificate(row):
    name=row.get('name','')
    if row.get('expiration_date'):return name+' · Expires '+row['expiration_date']
    if row.get('does_not_expire'):return name+' · No expiration'
    return name


def display(data):
    if not data.get('compact_skills') and not data.get('separate_certifications'):return data
    result=copy.deepcopy(data)
    for section in result.get('sections',[]) if data.get('compact_skills') else []:
        for entry in section.get('entries',[]):
            if entry.get('category')!='skills':continue
            if certifications.is_group(entry):
                rows=certifications.rows(entry)
                known={key:certificate(row) for row in rows for key in (certifications.text(row),row['name'])}
                # Preserve explicit custom wording rather than guessing which credential it means.
                entry['bullets']=[known.get(value,value) for value in entry.get('bullets',[])]
                for field in ('organization','location','dates','details'):entry[field]=''
            else:
                items=entry.get('content_items',[])
                entry['bullets']=[RATING.sub('',value) if not items or n>=len(items) or items[n].get('field')=='skill' else value for n,value in enumerate(entry.get('bullets',[]))]
    if result.get('separate_certifications'):
        sections=[];certificates=[]
        for section in result.get('sections',[]):
            regular=[]
            for entry in section.get('entries',[]):
                if entry.get('category')=='skills' and certifications.is_group(entry):certificates.append(entry)
                else:regular.append(entry)
            if regular or section['title']!='Certifications':sections.append({**section,'entries':regular})
        if certificates:
            position=next((n+1 for n,s in enumerate(sections) if s['title']=='Skills'),len(sections))
            sections.insert(position,{'title':'Certifications','entries':certificates})
        result['sections']=sections
    return result


def display_dates(value):
    """Expand known months without inventing missing month/day precision."""
    from datetime import date
    def expand(match):
        try:return date(int(match[1]),int(match[2]),1).strftime('%B %Y')
        except ValueError:return match[0]
    text=re.sub(r'(?<!\d)(\d{4})-(\d{2})(?:-\d{2})?(?!\d)',expand,str(value))
    for index,month in enumerate(('January','February','March','April','May','June','July','August','September','October','November','December'),1):
        text=re.sub(r'\b'+month[:3]+r'\.?(?=\s+\d{4})',month,text,flags=re.I)
    return text
