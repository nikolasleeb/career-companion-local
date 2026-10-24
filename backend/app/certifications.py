"""User-reviewed credentials and private certificate attachments; no AI or verification."""
import re
from . import db
from .network import ServiceError


def is_group(data):
    return data.get('category')=='skills' and (bool(data.get('certification_items')) or bool(re.search(r'certific|licen[cs]e',data.get('title',''),re.I)))


def rows(data):
    if data.get('certification_items'): return data['certification_items']
    if not is_group(data): return []
    names=[v['name'] for v in data.get('skill_items',[]) if v.get('name')]
    if not names: names=[v.strip() for v in re.split(r'[,;\n]+',data.get('tools') or data.get('description','')) if v.strip()]
    return [{'name':name} for name in names]


def text(row):
    parts=[row['name']]
    if row.get('issuer'): parts.append(row['issuer'])
    for key,label in [('earned_date','Earned'),('valid_from','Valid from'),('expiration_date','Expires')]:
        if row.get(key): parts.append(label+' '+row[key])
    if row.get('does_not_expire'): parts.append('Does not expire')
    if row.get('credential_id'): parts.append('Credential ID: '+row['credential_id'])
    if row.get('credential_url'): parts.append(row['credential_url'])
    return ' · '.join(parts)


def validate_documents(user_id,data):
    for row in data.get('certification_items',[]):
        if row.get('document_id'):
            record=db.get(user_id,row['document_id'])
            if not record or record['kind']!='document' or record['data'].get('purpose')!='certificate':
                raise ServiceError('Choose a certificate uploaded to this account.')


def inspect_file(filename,raw):
    """Validate bounded supported formats without executing or rendering active content."""
    import io
    from pathlib import Path
    from pypdf import PdfReader
    from PIL import Image
    suffix=Path(filename).suffix.lower()
    if not raw or len(raw)>10*1024*1024: raise ServiceError('Choose a certificate up to 10 MB.')
    try:
        if suffix=='.pdf' and raw.startswith(b'%PDF-'):
            pdf=PdfReader(io.BytesIO(raw))
            if pdf.is_encrypted or not 1<=len(pdf.pages)<=30: raise ValueError()
            return 'application/pdf'
        if suffix in ('.png','.jpg','.jpeg'):
            with Image.open(io.BytesIO(raw)) as img:
                if img.format not in ('PNG','JPEG') or (suffix=='.png')!=(img.format=='PNG'): raise ValueError()
                if img.width*img.height>40_000_000: raise ValueError()
                img.verify()
            return 'image/png' if suffix=='.png' else 'image/jpeg'
    except Exception:
        raise ServiceError('The certificate could not be read. Use a valid PDF (up to 30 pages), PNG, or JPEG.') from None
    raise ServiceError('Use a PDF, PNG, or JPEG certificate.')
