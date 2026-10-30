"""New list continuation support preserves old paragraphs, source fields and records."""
from app import resume_data,db
from test_supporting_details import experience

def test_explicit_bullets_own_indented_continuations_only():
 assert resume_data.profile_bullets('• Develop rules\n  and test them\n• Present results')==['Develop rules and test them','Present results']
 assert resume_data.profile_bullets('- First\n\tcontinued\n* Second')==['First continued','Second']
 assert resume_data.profile_bullets('Paragraph one. Still one.\n  Another paragraph')==['Paragraph one. Still one.','Another paragraph']
 assert resume_data.profile_bullets('• First\n\n  Separate\n• ')==['First','Separate']

def test_resume_keeps_accomplishment_attribution_without_duplicate_markers():
 data={'category':'employment','title':'Fictional engineer','organization':'Example','description':'• Develop rules\n  and test behavior','accomplishments':'• Presented results\n  to the committee','contribution':'Existing personal context.'}
 result=resume_data.entry_snapshot(data,'fictional',granular=True)
 assert result['bullets']==['Develop rules and test behavior','Existing personal context.','Presented results to the committee']
 assert [(v['text'],v['field']) for v in result['content_items']]==[('Develop rules and test behavior','description'),('Existing personal context.','contribution'),('Presented results to the committee','accomplishment')]
 assert data['description']=='• Develop rules\n  and test behavior'

def test_other_profile_fields_and_old_paragraph_item_ids_unchanged():
 for kind in ('employment','volunteering','project','education','coursework'):
  data={'category':kind,'title':'Fictional role','description':'First paragraph. Second sentence.\nAnother paragraph.','accomplishments':'Completed something.'}
  result=resume_data.entry_snapshot(data,'fictional')
  assert result['bullets']==['First paragraph. Second sentence.','Another paragraph.','Completed something.']
 # Only the fields using the new editor interpret indented continuations.
 project=resume_data.entry_snapshot({'category':'project','title':'Project','description':'• First\n  continued'},'fictional')
 assert project['bullets']==['First','continued']

def test_save_reopen_and_backup_restore_keep_plain_strings_exactly(client,account):
 text='• Investigated the issue\n  and documented the findings\n• Shared results'
 row=experience(client,'employment','Fictional role',description=text,accomplishments='• Presented results')
 assert db.get(account['id'],row['id'])['data']['description']==text
 raw=client.get('/api/account/export').json()
 import json
 restored=client.post('/api/account/import',files={'file':('bullets.json',json.dumps(raw).encode(),'application/json')});assert restored.status_code==200,restored.text
 rows=[r for r in db.list_entities(account['id'],'experience') if r['data']['title']=='Fictional role']
 assert len(rows)==2 and all(r['data']['description']==text for r in rows)


import pytest
@pytest.mark.parametrize('format',['txt','docx','pdf'])
def test_exports_render_a_continued_item_as_one_bullet(format):
 import io
 from app import documents
 data={'name':'Fictional Person','sections':[{'title':'Work Experience','entries':[resume_data.entry_snapshot({'category':'employment','title':'Fictional engineer','description':'• Develop rules\n  and test behavior\n• Document results','accomplishments':'• Presented findings\n  to the committee'},'fictional')]}]}
 raw,mime=documents.export_resume(data,format)
 if format=='txt':text=raw.decode()
 elif format=='docx':
  from docx import Document
  paragraphs=[p.text for p in Document(io.BytesIO(raw)).paragraphs]
  assert 'Develop rules and test behavior' in paragraphs
  assert 'Presented findings to the committee' in paragraphs
  text='\n'.join(paragraphs)
 else:
  from pypdf import PdfReader
  text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
 assert text.count('Develop rules and test behavior')==1
 assert text.count('Presented findings to the committee')==1
 assert '• •' not in text and '- •' not in text
