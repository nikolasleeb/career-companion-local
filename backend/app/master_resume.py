"""Full reviewed Profile export, with no model call or one-page fitting."""
import copy,io,json
from fastapi import APIRouter,Depends,HTTPException,Query,Response
from . import auth,db,documents,resume_data,project_structure as structure,course_evidence,profile_answers,certifications,skill_details
router=APIRouter()
CONTACT=('name','contact','contact_reviewed','email','phone','city','state','country','county','website','linkedin','github')

def project_month(value):
 from .graduation_defaults import interval
 import calendar
 span=interval(value)
 if not span:return value or ''
 first,last=span
 return str(first.year) if first.month==1 and first.day==1 and last.month==12 and last.day==31 else calendar.month_name[first.month]+' '+str(first.year)

def project_dates(data):
 if data.get('start_date') or data.get('end_date'):return ' – '.join(filter(None,[project_month(data.get('start_date')),project_month(data.get('end_date'))]))
 import re
 return ' – '.join(project_month(part.strip()) for part in re.split(r'\s*[–—]\s*|\s+-\s+',data.get('dates','')))

def snapshot(user):
 with db.connect() as c:
  c.execute('BEGIN')
  settings=json.loads(c.execute('SELECT settings FROM users WHERE id=?',(user,)).fetchone()[0]);profile={k:settings.get(k) for k in CONTACT}
  rows=[db.decode(r) for r in c.execute("SELECT * FROM entities WHERE user_id=? AND kind IN ('experience','profile_answer') ORDER BY created_at,id",(user,))]
 entries=[r for r in rows if r['kind']=='experience'];known={r['id']:r for r in entries}
 details=[r for r in rows if r['kind']=='profile_answer' and r['data'].get('answer_kind')=='experience' and r['data'].get('status')=='confirmed']
 confirmed={r['id']:r for r in entries if r['data'].get('confirmed')}
 omitted={'draft_entries':sum(not r['data'].get('confirmed') for r in entries),'draft_details':sum(r['kind']=='profile_answer' and r['data'].get('status')=='draft' for r in rows),'archived_details':sum(r['kind']=='profile_answer' and r['data'].get('status')=='archived' for r in rows),'unattached_details':0}
 blocks=[];pending=[]
 def add(kind,text,depth=0):
  if str(text or '').strip():blocks.append({'kind':kind,'text':str(text),'depth':depth})
 def ordered(values):
  from .resume_builder import chronological_key
  return sorted(values,key=lambda r:(chronological_key(r['data']),r['created_at']),reverse=True)
 def answers(rid,course='',skill=''):
  context=skill or rid+(':'+course if course else '')
  result=[]
  for a in details:
   d=a['data'];refs=d.get('course_refs',[])
   if rid not in profile_answers.experience_ids(d):continue
   ref=d.get('skill_ref') or {}
   if skill and ref!={'experience_id':rid,'skill_id':skill}:continue
   if not skill and ref:continue
   if course and not any(v['education_id']==rid and v['course_id']==course for v in refs):continue
   if not course and refs:continue
   result.append(a)
  return sorted(result,key=lambda a:(a['data'].get('detail_order',{}).get(context,100000),a['created_at'],a['id']))
 def detail_blocks(rid,depth=0,course='',project=None,parent=None,skill='',label=True,seen=None,exclude=()):
  values=[]
  for a in answers(rid,course,skill):
   if a['id'] in exclude or seen is not None and a['id'] in seen:continue
   if project is not None:
    scope=structure.scope_for_detail(a['data'],rid,project)
    if parent is not None and structure.timeline_enabled(project) and not structure.permits(scope,project,parent):continue
   if seen is not None:seen.add(a['id'])
   values.append(a['data']['text'])
  if values:
   if label:add('label','Supporting Details',depth)
   for text in values:
    add('bullet',text,depth+1 if label else depth)
    if course:blocks[-1]['emphasis']='course_detail'
 def project(r,parent=None,depth=1,seen=None):
  d=r['data'];shared=structure.timeline_enabled(d)
  stage=next((v for v in structure.stages(d) if v['parent_id']==parent),None) if shared else None
  add('entry',d['title'],depth)
  dates=' – '.join(filter(None,[project_month(stage.get('start_date')),project_month(stage.get('end_date'))])) if stage else project_dates(d)
  if stage and not dates:
   dates=project_dates(d)
   if dates and len(structure.parents(d))>1:dates='Whole project dates: '+dates
  add('meta',dates,depth)
  if shared and parent is None and (any(v['scope']['kind']=='unassigned' for v in structure.statements(d)) or any(structure.scope_for_detail(a['data'],r['id'],d)['kind']=='unassigned' for a in answers(r['id']))):add('meta','Timeline assignment pending',depth)
  for v in structure.statements(d):
   if parent is None or not shared or structure.permits(v['scope'],d,parent):
    add('bullet',('My contribution: ' if v['field']=='contribution' and not d.get('individual_project') else '')+v['text'],depth+1)
  if d.get('tools'):add('meta','Tools: '+d['tools'],depth)
  for url in __import__('app.models',fromlist=['project_links']).project_links(d):add('meta',url,depth)
  detail_blocks(r['id'],depth+1,project=d,parent=parent,seen=seen)
 pending_skill_details=set()
 def normal(r):
  d=r['data'];display=copy.deepcopy(d)
  children=ordered([p for p in confirmed.values() if p['data']['category']=='project' and r['id'] in structure.parents(p['data'])])
  # One saved detail can have legacy links to both the parent and its project.
  # Prefer its project placement, deduplicating IDs only within this subtree.
  nested_detail_ids={a['id'] for p in children for a in answers(p['id']) if not structure.timeline_enabled(p['data']) or structure.permits(structure.scope_for_detail(a['data'],p['id'],p['data']),p['data'],r['id'])}
  seen=set()
  if d['category']=='education':display['relevant_courses']=''
  if skill_details.is_group(d):display.update(skill_items=[],tools='')
  entry=resume_data.entry_snapshot(display,r['id']);add('entry',entry['title']);add('meta',entry['details'])
  for v in entry['bullets']:add('bullet',v,1)
  if skill_details.is_group(d):
   for skill in skill_details.items(d,r['id']):
    name=skill['name']+(' ('+skill['level']+', self-rated)' if skill.get('level','unknown')!='unknown' else '')
    add('skill',name,1);detail_blocks(r['id'],2,skill=skill['id'],label=False)
   pending=[a for a in answers(r['id']) if a['id'] not in pending_skill_details]
   if pending:
    add('label','Skill details awaiting assignment',1)
    for a in pending:add('bullet',a['data']['text'],2);pending_skill_details.add(a['id'])
  else:detail_blocks(r['id'],1,seen=seen,exclude=nested_detail_ids)
  if d['category'] in ('education','coursework'):
   courses=course_evidence.classes(r)
   if courses and d['category']=='education':add('subsection','Coursework',1)
   for course in courses:
    if d['category']=='education':add('course',course['title'],1)
    detail_blocks(r['id'],2,course['id'],label=False)
  if children:
   add('subsection','Projects',1)
   for p in children:project(p,r['id'],2,seen=seen)
 for category,title in [('education','Education'),('employment','Work Experience'),('volunteering','Volunteering'),('coursework','Additional Coursework'),('skills','Skills'),('certifications','Certifications')]:
  values=ordered([r for r in confirmed.values() if (r['data']['category']==category and (category!='skills' or not certifications.is_group(r['data']))) or (category=='certifications' and certifications.is_group(r['data']))])
  if values:
   add('section',title)
   for r in values:normal(r)
 standalone=[p for p in confirmed.values() if p['data']['category']=='project' and not any(id in confirmed for id in structure.parents(p['data']))]
 if standalone:
  add('section','Projects')
  for p in ordered(standalone):project(p,None,0)
 for p in confirmed.values():
  d=p['data']
  if not structure.timeline_enabled(d) or p in standalone:continue
  items=[v['text'] for v in structure.statements(d) if v['scope']['kind']=='unassigned']
  supporting=[a['data']['text'] for a in answers(p['id']) if structure.scope_for_detail(a['data'],p['id'],d)['kind']=='unassigned']
  if items or supporting:pending.append((d['title'],items,supporting))
 if pending:
  add('section','Projects with timeline assignments pending')
  for title,items,supporting in pending:
   add('entry',title);add('meta','Timeline assignment pending')
   for v in items:add('bullet',v,1)
   if supporting:add('label','Supporting Details',1)
   for v in supporting:add('bullet',v,2)
 for a in details:
  if not any(id in confirmed for id in profile_answers.experience_ids(a['data'])):omitted['unattached_details']+=1
 value={'name':profile.get('name') or 'Master Resume','contact_lines':resume_data.contact_lines(profile),'blocks':blocks,'omitted':omitted,'pending_projects':len(structure.pending_assignments(entries,details)),'pending_project_assignments':structure.pending_assignments(entries,details)}
 return {**value,'revision':structure.digest(value)}

def render_docx(value):
 from docx import Document
 from docx.shared import Inches,Pt,RGBColor
 from docx.enum.text import WD_ALIGN_PARAGRAPH,WD_TAB_ALIGNMENT
 from docx.oxml import OxmlElement
 from docx.oxml.ns import qn
 doc=Document();section=doc.sections[0]
 section.top_margin=section.bottom_margin=Inches(.65);section.left_margin=section.right_margin=Inches(.75)
 normal=doc.styles['Normal'];normal.font.name='Calibri';normal.font.size=Pt(11);normal.font.bold=False
 normal.paragraph_format.space_after=Pt(4);normal.paragraph_format.line_spacing=1.08
 from docx.enum.style import WD_STYLE_TYPE
 for name,size in [('Title',22),('Subtitle',12),('Heading 1',16),('Heading 2',14),('Master Subsection',12.5),('Master Project',11.5),('Master Detail Label',10.5)]:
  if name not in doc.styles:doc.styles.add_style(name,WD_STYLE_TYPE.PARAGRAPH).base_style=normal
  style=doc.styles[name];style.font.name='Calibri';style.font.size=Pt(size);style.font.color.rgb=RGBColor(0,0,0)
  style.font.bold=name not in ('Title','Subtitle')
  style.font.italic=False;style.paragraph_format.keep_with_next=True
  style.paragraph_format.space_before=Pt(10);style.paragraph_format.space_after=Pt(4)
  props=style.element.pPr
  if props is not None:
   for border in list(props.findall(qn('w:pBdr'))):props.remove(border)
 # Dedicated bullet definitions avoid renderer/template-dependent list indentation.
 numbering=doc.part.numbering_part.element
 abstract_id=max([int(v.get(qn('w:abstractNumId'))) for v in numbering.findall(qn('w:abstractNum'))]+[-1])+1
 abstract=OxmlElement('w:abstractNum');abstract.set(qn('w:abstractNumId'),str(abstract_id))
 for depth in range(9):
  level=OxmlElement('w:lvl');level.set(qn('w:ilvl'),str(depth))
  for tag,val in [('start','1'),('numFmt','bullet'),('lvlText','•'),('lvlJc','left')]:
   child=OxmlElement('w:'+tag);child.set(qn('w:val'),val);level.append(child)
  props=OxmlElement('w:pPr');indent=OxmlElement('w:ind');indent.set(qn('w:left'),str(depth*360+216));indent.set(qn('w:hanging'),'216');props.append(indent);level.append(props);abstract.append(level)
 numbering.append(abstract)
 num_id=max([int(v.get(qn('w:numId'))) for v in numbering.findall(qn('w:num'))]+[0])+1
 num=OxmlElement('w:num');num.set(qn('w:numId'),str(num_id));ref=OxmlElement('w:abstractNumId');ref.set(qn('w:val'),str(abstract_id));num.append(ref);numbering.append(num)
 title=doc.add_paragraph(value['name'],'Title');title.paragraph_format.space_before=Pt(0)
 doc.add_paragraph('Full Master Resume','Subtitle')
 for line in value['contact_lines']:doc.add_paragraph(line)
 for index,b in enumerate(value['blocks']):
  kind=b['kind'];depth=b['depth'];bullet=kind in ('bullet','course','skill')
  style={'section':'Heading 1','entry':'Master Project' if depth else 'Heading 2','subsection':'Master Subsection','label':'Master Detail Label'}.get(kind,'Normal')
  p=doc.add_paragraph(b['text'],style);fmt=p.paragraph_format
  fmt.left_indent=Inches(.25*depth+(.15 if bullet else 0));fmt.first_line_indent=Inches(-.15 if bullet else 0)
  fmt.keep_with_next=kind in ('section','entry','label','subsection')
  fmt.keep_together=False;fmt.widow_control=True
  if bullet:
   props=p._p.get_or_add_pPr();number=OxmlElement('w:numPr')
   for tag,val in [('ilvl',str(min(depth,8))),('numId',str(num_id))]:
    child=OxmlElement('w:'+tag);child.set(qn('w:val'),val);number.append(child)
   props.append(number);fmt.tab_stops.add_tab_stop(Inches(.25*depth+.15),WD_TAB_ALIGNMENT.LEFT)
   # A course/skill stays with its first detail, never with the following course.
   fmt.keep_with_next=kind in ('course','skill') and index+1<len(value['blocks']) and value['blocks'][index+1]['depth']>depth
  if kind in ('label','subsection'):
   fmt.space_before=Pt(7);fmt.space_after=Pt(3)
  if kind=='meta':
   fmt.keep_with_next=index+1<len(value['blocks']) and value['blocks'][index+1]['kind'] not in ('section','entry')
   fmt.space_after=Pt(4)
   for run in p.runs:run.font.size=Pt(10);run.font.color.rgb=RGBColor.from_string('444444')
 footer=section.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER;footer.add_run('Page ')
 field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
 doc.core_properties.title='Full Master Resume';doc.core_properties.author='';doc.core_properties.last_modified_by=''
 stream=io.BytesIO();doc.save(stream);return stream.getvalue()

@router.get('/api/profile/master-resume')
def preview(user=Depends(auth.current)):
 value=snapshot(user['id']);return {k:v for k,v in value.items() if k!='blocks'}|{'statement_count':sum(b['kind']=='bullet' for b in value['blocks'])}
@router.get('/api/profile/master-resume/export/{format}')
def export(format:str,revision:str=Query(min_length=64,max_length=64),user=Depends(auth.current)):
 if format not in ('pdf','docx'):raise HTTPException(404,'Choose PDF or Word.')
 value=snapshot(user['id'])
 if revision!=value['revision']:raise HTTPException(409,'Your Profile changed. Refresh the export summary before downloading.')
 raw=render_docx(value)
 if format=='pdf':raw=documents.docx_pdf(raw)
 name=resume_data._filename_part(value['name']) or 'Profile'
 return Response(raw,media_type='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':'attachment; filename="'+__import__('urllib.parse',fromlist=['quote']).quote(name)+'-Master-Resume.'+format+'"','Cache-Control':'no-store'})
