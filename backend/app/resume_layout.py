"""Rendered-PDF layout checks; no provider calls and no text changes."""
import base64
import copy
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from defusedxml import ElementTree
from . import resume_builder,resume_presentation
from .network import ServiceError

def words(value):return re.findall(r'[a-z0-9]+',value.casefold())

def one_page_request(text):
    return bool(re.search(r'\b(?:one|single|1)[\s-]+page\b',text,re.I))

def fit(snapshot,rows,initial,protected_item_ids=None):
    def measure(value):
        result=render(value)
        return result['layout']['pages'],result['artifacts']
    return resume_builder.fit(snapshot,rows,initial,protected_item_ids,measure)

def text_lines(pdf):
    executable=shutil.which('pdftotext')
    if not executable:raise ServiceError('Layout inspection needs the PDF tools bundled in the Docker app.')
    with tempfile.TemporaryDirectory(prefix='nextstep-layout-') as folder:
        source=Path(folder)/'resume.pdf';source.write_bytes(pdf)
        try:
            result=subprocess.run([executable,'-bbox-layout',str(source),'-'],capture_output=True,check=True,timeout=30)
            tree=ElementTree.fromstring(result.stdout)
        except (OSError,subprocess.SubprocessError,ElementTree.ParseError):raise ServiceError('The generated PDF could not be inspected. Your previous preview is intact.') from None
    lines=[]
    for page_number,page in enumerate(tree.findall('.//{*}page'),1):
        for line in page.findall('.//{*}line'):
            text=' '.join(w.text or '' for w in line.findall('{*}word'))
            if text.strip():lines.append({'page':page_number,'text':text,'tokens':words(text),'width':float(line.get('xMax','0'))-float(line.get('xMin','0'))})
    return lines

def wrapped_items(pdf,snapshot):
    """Measure actual narrative wrapping, not character-count estimates."""
    lines=text_lines(pdf);result=[]
    for section in snapshot['sections']:
        for entry in section['entries']:
            for item in entry.get('content_items',[]):
                if item['field'] not in ('description','contribution','accomplishment'):continue
                expected=words(item['text'])
                if len(expected)<4:continue
                for n,line in enumerate(lines):
                    if line['tokens'][:4]!=expected[:4]:continue
                    found=[];matched=[]
                    for candidate in lines[n:n+12]:
                        found+=candidate['tokens'];matched.append(candidate)
                        if found==expected or found!=expected[:len(found)]:break
                    if found==expected and len(matched)>1:
                        result.append({'record_id':entry['source_id'],'item_id':item['item_id'],'line_count':len(matched),'target_lines':len(matched)-1,'last_line_words':len(matched[-1]['tokens']),'last_line':matched[-1]['text']})
                    break
    return result

def inspect(pdf,snapshot):
    snapshot=resume_presentation.display(snapshot)
    lines=text_lines(pdf);issues=[]
    for section in snapshot['sections']:
        for entry in section['entries']:
            items=entry.get('content_items',[])
            for index,bullet in enumerate(entry.get('bullets',[])):
                expected=words(bullet)
                if len(expected)<9:continue
                for i,line in enumerate(lines):
                    if not line['tokens'] or line['tokens'][:4]!=expected[:4]:continue
                    found=[];matched=[]
                    for candidate in lines[i:i+6]:
                        found+=candidate['tokens'];matched.append(candidate)
                        if found==expected:break
                        if found!=expected[:len(found)]:break
                    if found==expected and len(matched)>1 and len(matched[-1]['tokens'])<=2 and matched[-1]['width']<110:
                        issues.append({'kind':'dangling_words','record_id':entry['source_id'],'item_id':items[index]['item_id'] if index<len(items) else '', 'text':entry['title']+': this bullet ends with a very short carryover line (“'+matched[-1]['text']+'”).','ending':matched[-1]['text']})
                    break
    return issues[:12]

def render(snapshot):
    value=copy.deepcopy(snapshot);value.pop('artifacts',None);value['schema_version']=4
    pages,artifacts=resume_builder.render(value)
    issues=inspect(base64.b64decode(artifacts['pdf']),value)
    if pages!=1:
        longest=sorted([e for s in value['sections'] for e in s['entries']],key=lambda e:-sum(len(b) for b in e['bullets']))[:3]
        issues.insert(0,{'kind':'overflow','record_id':'','item_id':'','text':f'This draft fills {pages} pages. Review '+', '.join(e['title'] for e in longest)+'. Shorten content or omit lower-priority items before saving.'})
    value['layout']={'pages':pages,'body_font_pt':10.5,'validated':pages==1,'issues':issues,'wrapped_items':wrapped_items(base64.b64decode(artifacts['pdf']),value),'renderer':'DOCX → PDF','format_version':4}
    value['artifacts']=artifacts
    return value
