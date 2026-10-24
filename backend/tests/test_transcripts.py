from app import transcript_parser, db

TEXT='''Fictional University
Student ID: 00000000
Fall 2025
INFO 201  Foundations of Information  3.00  A  12.00
CSC 110 | Introduction to Programming | 3.00 | B+
STAT 201 Probability and Statistics 3.00 A 12.00
INFO 201  Foundations of Information  3.00  A  12.00
Spring 2026 In Progress
DATA 301  Data Mining  3.00  IP
MATH 225  Linear Algebra  3.00  W
'''

def test_parse_courses_and_status_without_inventing_completion():
    result=transcript_parser.parse(TEXT)
    assert [c['title'] for c in result['courses']]==['Foundations of Information','Introduction to Programming','Probability and Statistics','Data Mining','Linear Algebra']
    assert result['courses'][0]['status']=='listed'
    assert all(c['status']=='needs_review' for c in result['courses'][-2:])
    assert all(c['excerpt'] in TEXT for c in result['courses'])
    assert not transcript_parser.parse('Student GPA 4.0\nCumulative Credits 30')['courses']

def test_transcript_endpoint_requires_login(client):
    assert client.post('/api/transcripts/parse',files={'file':('transcript.txt',TEXT)}).status_code==401

def test_transcript_endpoint_is_transient_and_preserves_master(client,account):
    before=client.get('/api/workspace').json()
    response=client.post('/api/transcripts/parse',files={'file':('transcript.txt',TEXT)})
    assert response.status_code==200,response.text
    assert len(response.json()['courses'])==5
    assert client.get('/api/workspace').json()==before
    assert not list((db.config.DATA_DIR/'uploads').glob('**/*'))
    response=client.post('/api/transcripts/parse',files={'file':('transcript.exe',TEXT)})
    assert response.status_code==400


def test_text_based_pdf_course_upload(client,account):
    import io
    from reportlab.pdfgen import canvas
    stream=io.BytesIO(); pdf=canvas.Canvas(stream)
    pdf.drawString(50,750,'Fictional transcript')
    pdf.drawString(50,730,'INFO 301 Database Systems 3.00 A 12.00')
    pdf.save()
    response=client.post('/api/transcripts/parse',files={'file':('transcript.pdf',stream.getvalue(),'application/pdf')})
    assert response.status_code==200,response.text
    assert response.json()['courses'][0]['title']=='Database Systems'


def test_docx_course_upload(client,account,monkeypatch):
    import io
    from docx import Document
    from app import documents
    monkeypatch.setattr(documents,'docx_pages',lambda raw:1)
    doc=Document();table=doc.add_table(rows=1,cols=4)
    for cell,value in zip(table.rows[0].cells,['CSC 110','Programming Fundamentals','3.00','A']): cell.text=value
    stream=io.BytesIO();doc.save(stream)
    response=client.post('/api/transcripts/parse',files={'file':('transcript.docx',stream.getvalue())})
    assert response.status_code==200,response.text
    assert response.json()['courses'][0]['title']=='Programming Fundamentals'


PORTAL='''Course: DATA 510
Description: Statistical Foundations
Term: Fall 2026
Units: 3.00
Status: In Progress
Course: DATA 520
Description: Data Visualizatio
Term: Fall 2026
Units: 3.00
Status: In Progress
Course: MIS 550
Description: Applied AI for Business
Term: Fall 2026
Units: 3.00
Status: In Progress
Course: DATA 690
Description: Internship
Term: Summer 2026
Grade: S
Units: 3.00
Status: Taken
Course: DATA 530
Description: Cloud Data Warehousing
Term: Spring 2026
Grade: A
Units: 3.00
Status: Taken
Course History
Student ID: 00000000
https://fictional.invalid/history 1/2
Course: DATA 570
Description: SQL Databases
Term: Spring 2026
Grade: A
Units: 3.00
Status: Taken
Course: MIS 580
Description: Big Data Methods
Term: Spring 2026
Grade: A
Units: 3.00
Status: Taken
Course: DATA 500
Description: Data Science Foundations
Term: Fall 2025
Grade: A
Units: 3.00
Status: Taken
Course: DATA 540
Description: Machine Learning Introduction
Term: Fall 2025
Grade: W
Units: 3.00
Status: Taken
Course: DATA 560
Description: Data Mining
Term: Fall 2025
Grade: A
Units: 3.00
Status: Taken
Copyright Fictional University
'''


def test_portal_labelled_courses_preserve_titles_and_conservative_statuses():
    result=transcript_parser.parse(PORTAL)
    assert len(result['courses'])==10
    assert sum(c['status']=='listed' for c in result['courses'])==6
    assert sum(c['status']=='needs_review' for c in result['courses'])==4
    assert result['courses'][1]['title']=='Data Visualizatio'  # Never complete a clipped source title.
    assert result['courses'][8]['status']=='needs_review'  # Taken + W is not completed work.
    assert 'in progress' in result['courses'][0]['review_note']
    assert 'withdrawal' in result['courses'][8]['review_note']
    assert all('Student ID' not in c['excerpt'] and 'Copyright' not in c['excerpt'] for c in result['courses'])
    assert all('grade' not in c and 'gpa' not in c for c in result['courses'])


def test_labelled_fields_do_not_leak_between_courses_and_unknown_status_needs_review():
    result=transcript_parser.parse('''Course: DATA 101
Description: Introductory Analysis
Status: In Progress
Course: DATA 102
Term: Fall 2025
Grade: A
Status: Taken
Course: DATA 103
Description: Research Methods
Course: DATA 104
Description: Advanced Analysis
Status: Taken
''')
    assert [c['code'] for c in result['courses']]==['DATA 101','DATA 103','DATA 104']
    assert [c['status'] for c in result['courses']]==['needs_review','needs_review','listed']
    assert 'DATA 102' not in result['courses'][0]['excerpt']


def test_labelled_pdf_and_wrapped_field_values(client,account):
    import io
    from reportlab.pdfgen import canvas
    stream=io.BytesIO();pdf=canvas.Canvas(stream)
    for index,line in enumerate(['Course: DATA 410','Description:','Research Methods','Term: Fall 2025','Grade: A','Units: 3.00','Status: Taken']):
        pdf.drawString(50,750-index*20,line)
    pdf.save()
    response=client.post('/api/transcripts/parse',files={'file':('portal.pdf',stream.getvalue(),'application/pdf')})
    assert response.status_code==200,response.text
    assert [(c['code'],c['title'],c['status']) for c in response.json()['courses']]==[('DATA 410','Research Methods','listed')]
    assert not db.list_entities(account['id'],'document')


def test_repeated_course_with_adverse_status_is_not_preselected():
    result=transcript_parser.parse('''Course: DATA 410
Description: Research Methods
Grade: A
Status: Taken
Course: DATA 410
Description: Research Methods
Grade: W
Status: Taken
''')
    assert len(result['courses'])==1 and result['courses'][0]['status']=='needs_review'
    assert 'Grade: W' in result['courses'][0]['excerpt']


def test_labelled_transcript_remains_transient_and_provider_free(client,account,monkeypatch):
    from app import ai
    async def forbidden(*args,**kwargs):raise AssertionError('Transcript parsing must not call AI')
    monkeypatch.setattr(ai,'structured',forbidden)
    before=client.get('/api/workspace').json()
    response=client.post('/api/transcripts/parse',files={'file':('course-history.txt',PORTAL)})
    assert response.status_code==200 and len(response.json()['courses'])==10
    assert client.get('/api/workspace').json()==before
    assert not list((db.config.DATA_DIR/'uploads').glob('**/*'))


BANNER='''TRANSFER CREDIT ACCEPTED BY INSTITUTION
SubjectCourse Title GradeCreditHoursQuality Points
ENSC 1015 Environmental Foundations T 3.000 0.00
ENSC 1016 Environmental Foundations TR 3.000 0.00
INSTITUTION CREDIT
Term: Fall 2021
SubjectCourseCampusLevelTitle GradeCreditHoursQualityPoints
ARCH 1004 ExampleTownUG Campus as Community B 2.000 6.00
ARCH 1015 ExampleTownUG Foundation Design Laboratory B- 6.000 16.20
ENGL 1105 Remote UG First-Year Writing A 3.000 12.00
Term Totals (Undergraduate)
Attempt Passed Earned GPA
SubjectCourseCampusLevelTitle GradeCreditHoursQualityPoints
CS 1064 Research CenterGR Intro to Programming in Python A- 3.000 11.10
BIT 4604 Remote UG Data Gov, Privacy, Ethics A- 3.000 11.10
BIT 4424 ExampleTownUG Visualization Analytics B+ 3.000 9.90
'''


def test_campus_and_level_columns_are_not_course_titles():
    rows=transcript_parser.parse(BANNER)['courses']
    assert [r['title'] for r in rows[2:]]==['Campus as Community','Foundation Design Laboratory','First-Year Writing','Intro to Programming in Python','Data Gov, Privacy, Ethics','Visualization Analytics']
    assert all('ExampleTown' not in r['title'] and 'Remote UG' not in r['title'] and 'Research Center' not in r['title'] for r in rows)
    assert all(r['status']=='listed' for r in rows[2:])
    assert 'ExampleTownUG' in rows[2]['excerpt']  # The original evidence is unchanged.


def test_transfer_credit_markers_are_removed_and_flagged_for_school_review():
    rows=transcript_parser.parse(BANNER)['courses']
    assert [r['title'] for r in rows[:2]]==['Environmental Foundations']*2
    assert all(r['status']=='needs_review' and 'school attribution' in r['review_note'] for r in rows[:2])
    assert not any(key in rows[0] for key in ('grade','gpa','credits','campus'))


def test_campus_columns_remain_active_across_pdf_page_headers():
    text='''SubjectCourseCampusLevelTitle GradeCreditHoursQualityPoints
Unrelated report header
Page 2 of 7
DATA 410 ExampleTownUG Research Methods A 3.000 12.00
'''
    assert transcript_parser.parse(text)['courses'][0]['title']=='Research Methods'


def test_course_title_words_are_not_removed_without_campus_column_headers():
    text='''Subject Course Title Grade Credit Hours
DATA 410 Virtual UG Research Methods A 3.000 12.00
DATA 411 Plan A 3.000 A 12.00
DATA 412 Applied Calculus 2
'''
    assert [r['title'] for r in transcript_parser.parse(text)['courses']]==['Virtual UG Research Methods','Plan A','Applied Calculus 2']


def test_term_prefixed_degree_audit_rows_keep_titles_and_conservative_status():
    text='''Term Course Term Course Hours Grade Title Status
2021FA 21FA ARCH 1004 2.00 B Campus as Community
2021FA 21FA ENSC 1015 3.00 AP Environmental Foundations
2024WI 24WI BIT 3554 3.00 B Networks, Telecom, & Security
Page 2 of 2
2025SP 25SP BIT 3524 3.00 B Database Management and Desig
2025SP 25SP DATA 410 3.00 W Research Methods
2025SP 25SP DATA 411 3.00 IP Advanced Research
2025SP 25SP DATA 412 3.00 -- Data Applications
'''
    rows=transcript_parser.parse(text)['courses']
    assert len(rows)==7
    assert [r['title'] for r in rows[:4]]==['Campus as Community','Environmental Foundations','Networks, Telecom, & Security','Database Management and Desig']
    assert [r['status'] for r in rows]==['listed','needs_review','listed','listed','needs_review','needs_review','needs_review']
    assert 'Data Applications'==rows[-1]['title']


def test_changed_table_headers_do_not_strip_legitimate_title_prefixes():
    text='''SubjectCourseCampusLevelTitle GradeCreditHoursQualityPoints
DATA 410 ExampleTownUG Research Methods A 3.000 12.00
SubjectCourse Title GradeCreditHoursQuality Points
DATA 411 Virtual UG Methods T 3.000 0.00
'''
    rows=transcript_parser.parse(text)['courses']
    assert rows[1]['title']=='Virtual UG Methods' and rows[1]['status']=='needs_review'


def test_bad_campus_column_does_not_auto_select_a_guessed_title():
    row=transcript_parser.parse('SubjectCourseCampusLevelTitle GradeCreditHoursQualityPoints\nDATA 410 Unknown Campus Research Methods A 3.000 12.00')['courses'][0]
    assert row['status']=='needs_review' and row['title']=='Unknown Campus Research Methods'


def test_table_upload_is_provider_free_transient_and_preserves_current_profile(client,account,monkeypatch):
    from app import ai
    async def forbidden(*a,**k):raise AssertionError('No provider calls for transcript tables')
    monkeypatch.setattr(ai,'structured',forbidden)
    before=client.get('/api/workspace').json()
    response=client.post('/api/transcripts/parse',files={'file':('unofficial.txt',BANNER)})
    assert response.status_code==200 and response.json()['courses'][2]['title']=='Campus as Community'
    assert client.get('/api/workspace').json()==before
    assert not list((db.config.DATA_DIR/'uploads').glob('**/*'))
