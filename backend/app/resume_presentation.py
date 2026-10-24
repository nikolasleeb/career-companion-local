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
    if not data.get('compact_skills'):return data
    result=copy.deepcopy(data)
    for section in result.get('sections',[]):
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
    return result
