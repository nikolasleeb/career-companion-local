"""Bounded local suggestions from selectable certificate text. Never execute/fetch links.

AWS's inspected certificate layout paints static labels into artwork. Its dynamic
text lists name, issue date, expiration date, validation number and verification
URL in that order. Only the narrow recognizable layout below uses this fallback.
All output remains suggestions for the user's editable draft, never approval.
"""
import io
import re
from datetime import date,datetime
from pypdf import PdfReader
from .models import validate_link
from .network import ServiceError

VERSION='certificate-local-v2'
MONTH=r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)'
DATE=re.compile(r'\b(?:\d{4}-\d{2}-\d{2}|'+MONTH+r'\.?\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4}|\d{1,2}\s+'+MONTH+r'\.?[,]?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})\b',re.I)
LABELS={
 'name':r'(?:certification|certificate|credential)\s*(?:name|title)',
 'issuer':r'(?:issuing\s+(?:organization|organisation|authority)|issued\s+by|issuer)',
 'earned_date':r'(?:issue\s*date|issued\s+(?:on|date)|date\s+(?:issued|earned)|earned\s*(?:on|date)|awarded\s*(?:on|date))',
 'valid_from':r'(?:valid\s+from|effective\s+(?:date|from)|validity\s+start)',
 'expiration_date':r'(?:expiration\s*date|expiry\s*date|expires(?:\s+on)?|valid\s+(?:until|through))',
 'credential_id':r'(?:validation\s*(?:number|id)|credential\s*(?:id|number)|certificate\s*(?:id|number)|certification\s*(?:id|number))',
 'credential_url':r'(?:validate\s+at|verification\s*(?:url|link)|credential\s*(?:url|link))',
}


def calendar(value):
    value=re.sub(r'\bSept\b','Sep',value,flags=re.I)
    cleaned=re.sub(r'(\d)(st|nd|rd|th)\b',r'\1',value,flags=re.I).replace(',','').replace('.','').strip()
    if re.fullmatch(r'\d{1,2}[/-]\d{1,2}[/-]\d{4}',cleaned):
        first,second,year=map(int,re.split(r'[/-]',cleaned))
        if first<=12 and second<=12 and first!=second:return None
        try:return date(year,second,first).isoformat() if first>12 else date(year,first,second).isoformat()
        except ValueError:return None
    for pattern in ('%Y-%m-%d','%B %d %Y','%b %d %Y','%d %B %Y','%d %b %Y'):
        try:return datetime.strptime(cleaned,pattern).date().isoformat()
        except ValueError:continue
    return None


def parse_pdf(raw):
    if not raw or len(raw)>10*1024*1024:raise ServiceError('Choose a certificate up to 10 MB.')
    try:
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or not 1<=len(reader.pages)<=30:raise ValueError()
        pages=[];total=0;warnings=[]
        for number,page in enumerate(reader.pages,1):
            text=(page.extract_text() or '').replace('\r','')
            allowed=min(20000,60000-total)
            if len(text)>allowed:warnings.append('Page '+str(number)+' text was shortened for extraction.')
            text=text[:allowed];total+=len(text)
            pages.append((number,[line.strip() for line in text.splitlines() if line.strip()]))
            if total>=60000:
                warnings.append('Text was limited to 60,000 characters; check any omitted pages.');break
    except Exception:raise ServiceError('The PDF could not be read. Use an unlocked, text-based PDF up to 30 pages.') from None
    result=parse_pages(pages,len(reader.pages),warnings)
    targets=[number for number,lines in pages if not result['fields'] or sum(map(len,lines))<40]
    if targets:
        from . import certificate_ocr
        ocr=certificate_ocr.extract(raw,'application/pdf',targets)
        if ocr['pages']:
            by_number=dict(ocr['pages'])
            combined=[(number,lines+by_number.get(number,[])) for number,lines in pages]
            result=parse_pages(combined,len(reader.pages),warnings+ocr['warnings'])
            for field in result['fields'].values():
                if field['page'] in by_number:field['reason']='Text / local OCR · '+field['reason']
        else:result['warnings'].extend(ocr['warnings'])
        result.update(ocr_pages=[number for number,_ in ocr['pages']],incomplete=ocr['incomplete'])
        result['extraction_method']='text_and_ocr' if any(lines for _,lines in pages) else 'ocr'
        result['warnings'].append('Local OCR can misread names, dates and credential IDs. Check suggestions against the original certificate.')
    else:result.update(extraction_method='text',ocr_pages=[],incomplete=False)
    return result


def parse_certificate(raw,mime):
    if mime=='application/pdf':return parse_pdf(raw)
    if mime not in ('image/png','image/jpeg') or not raw or len(raw)>10*1024*1024:raise ServiceError('Choose a PDF, PNG or JPEG certificate up to 10 MB.')
    from . import certificate_ocr
    ocr=certificate_ocr.extract(raw,mime)
    result=parse_pages(ocr['pages'],1,ocr['warnings'])
    for field in result['fields'].values():field['reason']='Local OCR · '+field['reason']
    result.update(extraction_method='ocr',ocr_pages=[number for number,_ in ocr['pages']],incomplete=ocr['incomplete'])
    result['warnings'].append('Local OCR can misread names, dates and credential IDs. Check suggestions against the original certificate.')
    return result


def parse_pages(pages,page_count,warnings):
    warnings=list(warnings);total=sum(sum(map(len,lines)) for _,lines in pages)
    candidates={}
    def add(key,value,excerpt,page,reason='Labeled certificate text'):
        if not value or len(str(value))>({'name':200,'issuer':200,'credential_id':200,'credential_url':2000}.get(key,100)):return
        if key in ('earned_date','valid_from','expiration_date'):
            value=calendar(value)
            if not value:return
            if key=='earned_date' and value>date.today().isoformat():
                warnings.append('A future issue date needs manual review.');return
        if key=='credential_url':
            try:validate_link(value)
            except ValueError:return
        proposal={'value':value,'excerpt':excerpt[:600],'page':page,'reason':reason}
        if not any(v['value']==value for v in candidates.get(key,[])):candidates.setdefault(key,[]).append(proposal)
    for page,lines in pages:
        for i,line in enumerate(lines):
            for key,pattern in LABELS.items():
                match=re.fullmatch(r'\s*'+pattern+r'(?:\s*[:#–—-]\s*|\s+|$)(.*?)\s*',line,re.I)
                if not match:continue
                value=match.group(1).strip();excerpt=line
                if not value and i+1<len(lines):value=lines[i+1];excerpt+='\n'+value
                if key.endswith('_date') or key=='valid_from':
                    dates=list(DATE.finditer(value))
                    if len(dates)==1:add(key,dates[0].group(),excerpt,page)
                    elif value:warnings.append('An ambiguous or incomplete date was left blank.')
                elif key=='credential_url':
                    urls=re.findall(r'https?://[^\s<>]+',value)
                    if len(urls)==1:add(key,urls[0].rstrip('.,;'),excerpt,page)
                elif not any(re.match(pattern+r'\b',value,re.I) for pattern in LABELS.values()):add(key,value,excerpt,page)
            if re.fullmatch(r'(?:does\s+not\s+expire|no\s+expiration(?:\s+date)?|non[- ]expiring)',line,re.I):add('does_not_expire',True,line,page)
        # This fallback is deliberately single-page and single-credential only.
        names=[line for line in lines if re.fullmatch(r'AWS Certified [A-Za-z0-9 ()/&+\-]+',line)]
        dates=[(m.group(),calendar(m.group())) for line in lines for m in DATE.finditer(line)]
        ids=[line for line in lines if re.fullmatch(r'[a-fA-F0-9]{28,40}',line)]
        url='https://aws.amazon.com/verification'
        if page_count==1 and len(names)==1 and len(dates)==2 and len(ids)==1 and url in lines and all(value for _,value in dates) and dates[0][1]<=dates[1][1]:
            name=names[0]
            add('name',name,name,page,'Recognized AWS certificate heading')
            add('issuer','AWS',name,page,'AWS issuer shown in the credential heading')
            add('earned_date',dates[0][0],dates[0][0],page,'AWS certificate layout: Issue Date')
            add('expiration_date',dates[1][0],dates[1][0],page,'AWS certificate layout: Expiration Date')
            add('credential_id',ids[0],ids[0],page,'AWS certificate layout: Validation Number')
            add('credential_url',url,url,page,'AWS certificate verification address')
    fields={key:values[0] for key,values in candidates.items() if len(values)==1}
    for key,values in candidates.items():
        if len(values)>1:warnings.append(key.replace('_',' ').capitalize()+' has conflicting values; enter it manually.')
    if fields.get('does_not_expire') and fields.get('expiration_date'):
        fields.pop('does_not_expire');fields.pop('expiration_date');warnings.append('Conflicting expiration information was left for manual review.')
    if fields.get('expiration_date') and fields['expiration_date']['value']<max(fields.get('earned_date',{}).get('value',''),fields.get('valid_from',{}).get('value','')):
        fields.pop('expiration_date');warnings.append('Expiration precedes another date; check it manually.')
    if not total:warnings.append('No selectable text or readable OCR text was found. Try a clearer file or enter the details manually.')
    elif not fields:warnings.append('No confidently labeled fields were recognized. Enter the details manually.')
    return {'parser_version':VERSION,'pages':page_count,'fields':fields,'warnings':list(dict.fromkeys(warnings))}
