"""Conservative, local transcript course extraction. Never infer grades or credentials."""
import re

CODE = re.compile(r'^\s*(?:[•*]\s*)?([A-Z][A-Z&]{1,9})\s*[- ]?\s*(\d{2,4}[A-Z]?)\b\s*(?:[|:–—-]\s*)?(.+)$')
COURSE = re.compile(r'^\s*Course\s*:\s*([A-Z][A-Z&]{1,9})\s*[- ]?\s*(\d{2,4}[A-Z]?)\s*$',re.I)
FIELD = re.compile(r'^\s*(Description|Term|Grade|Units|Status)\s*:\s*(.*?)\s*$',re.I)
STATUS = re.compile(r'\b(in progress|in-progress|currently enrolled|registered|planned|withdrawn|withdrawal|failed|not completed)\b', re.I)
GRADE = r'(?:[A-DF][+-]?|AP|TP|TR|T|P|S|U|WF|W|IP|I|CR|NC|AU)'
TRANSFER_GRADE=re.compile(r'^(?:T|TR|TP|AP)$',re.I)
AUDIT_ROW=re.compile(r'^\s*\d{4}(?:FA|SP|SU|WI)\s+(?:\d{2}(?:FA|SP|SU|WI)\s+)?([A-Z][A-Z&]{1,9})\s+(\d{2,4}[A-Z]?)\s+\d+(?:\.\d+)?\s+('+GRADE+r'|--?|\*\*)\s+(.+?)\s*$')
REVIEW_GRADE = re.compile(r'^(?:W|WF|I|IP|NC|F|U|AU)[+-]?$',re.I)


def labelled_courses(lines):
    """Read bounded Course/Description/Term/Status blocks from student portals."""
    starts=[(i,COURSE.match(line)) for i,line in enumerate(lines) if COURSE.match(line)]
    blocks={}
    for position,(start,match) in enumerate(starts):
        end=starts[position+1][0] if position+1<len(starts) else len(lines)
        values={}; evidence=[lines[start]]
        for i in range(start+1,end):
            field=FIELD.match(lines[i])
            if not field:continue
            key,value=field.groups();key=key.lower()
            # Some PDF extractors place a field value on the following line.
            if not value and i+1<end and not FIELD.match(lines[i+1]):
                value=lines[i+1].strip()
            if key in values:continue  # Never borrow a later repeated field.
            values[key]=value;evidence.append(lines[i] if field.group(2) else lines[i]+' '+value)
        title=values.get('description','').strip()
        if len(title)<3 or not re.search(r'[A-Za-z]{3}',title):continue
        status=values.get('status','').strip();grade=values.get('grade','').strip()
        note=review_note(grade,status)
        if not note and status.casefold() not in ('taken','completed','complete','passed'):
            note='The course status is missing or unclear. Check before adding.'
        blocks[start]={'code':match.group(1).upper()+' '+match.group(2).upper(),'title':title[:250],
                       'status':'needs_review' if note else 'listed','review_note':note,
                       'excerpt':'\n'.join(evidence)[:1000]}
    return blocks


def review_note(grade='',status='',pending=False):
    if STATUS.search(status):return 'The source marks this course '+status.lower()+'. Check before adding.'
    if REVIEW_GRADE.fullmatch(grade):return 'The source grade indicates withdrawal, incomplete, failure, no credit, or audit. Check before adding.'
    if TRANSFER_GRADE.fullmatch(grade):return 'Transfer or examination credit: verify the course and school attribution before adding.'
    if pending:return 'The term or course status needs review before adding.'
    return ''


def row_title(tail):
    """Separate real numeric grade columns, never a title's final word/number alone."""
    normalized=re.sub(r'\s*\|\s*|\t+',' ',tail).strip()
    for pattern in [r'^(.+?)\s+\d+(?:\.\d+)?\s+('+GRADE+r')(?:\s+\d+(?:\.\d+)?)*\s*$',
                    r'^(.+?)\s+('+GRADE+r')\s+\d+(?:\.\d+)?(?:\s+\d+(?:\.\d+)?)*\s*$']:
        match=re.match(pattern,normalized)
        if match:return match.group(1).strip(),match.group(2)
    parts=[p.strip() for p in re.split(r'\s*\|\s*|\t+|\s{2,}',tail) if p.strip()]
    title=parts[0] if parts else tail.strip()
    # A credits-only decimal column can occur for a course still in progress.
    title=re.sub(r'\s+\d+\.\d+(?:\s+\d+\.\d+)*\s*$','',title)
    return title,''


def parse(text):
    courses=[];seen={};warnings=[];lines=text.splitlines()
    blocks=labelled_courses(lines);term_status=False;schema=''

    def append(course):
        key=(course['code'],course['title'].casefold())
        if key in seen:
            previous=courses[seen[key]]
            # A repeated course with conflicting status must not hide a warning.
            if course['status']=='needs_review':
                previous['status']='needs_review';previous['review_note']=course.get('review_note') or 'A repeated listing needs review.'
                if course['excerpt']!=previous['excerpt']:
                    previous['excerpt']=(previous['excerpt']+'\nRepeated listing:\n'+course['excerpt'])[:2000]
            return
        seen[key]=len(courses);courses.append({'id':str(len(courses)),**course})

    for i,line in enumerate(lines):
        if i in blocks:
            append(blocks[i]);continue
        header=re.sub(r'[^a-z]','',line.casefold())
        if all(word in header for word in ('subject','course','title','grade')):
            schema='campus' if 'campus' in header and 'level' in header else 'standard'
            continue
        if all(word in header for word in ('term','course','hours','grade','title')):
            schema='audit';continue
        if header.startswith(('termtotals','transcripttotals')):
            schema='';continue
        if re.search(r"\b(?:spring|summer|fall|winter)\s+20\d\d\b",line,re.I):
            term_status=bool(STATUS.search(line))
        audit=AUDIT_ROW.match(line) if schema=='audit' else None
        if audit:
            subject,number,grade,title=audit.groups()
            note=review_note(grade,pending=bool(STATUS.search(line)))
            if grade in ('-','--','**'):note='The source grade or status is unclear. Check before adding.'
        else:
            match=CODE.match(line)
            if not match:continue
            subject,number,tail=match.groups();title,grade=row_title(tail)
            note=review_note(grade,pending=term_status or bool(STATUS.search(tail)))
            if schema=='campus':
                # PDF text can join the campus and level (e.g. ExampleTownUG).
                # Only remove this prefix when the table declares both columns.
                columns=re.match(r'^.+?\s*(?:UG|GR|PR|ND)\s+(.+)$',title)
                if columns:title=columns.group(1).strip()
                else:note='Could not separate campus, level and title. Check the source before adding.'
        title=STATUS.sub('',title).strip(' |:;,-–—')
        if len(title)<3 or not re.search(r'[A-Za-z]{3}',title):continue
        if re.match(r'^(?:total|term|cumulative|gpa|credits|hours)\b',title,re.I):continue
        append({'code':subject+' '+number,'title':title[:250],'status':'needs_review' if note else 'listed','review_note':note,'excerpt':line[:1000]})
    if not courses:warnings.append('No course rows were recognized. Check the extracted text and copy course names manually. Scanned transcripts need selectable or pasted text.')
    warnings.append('Review course titles and school attribution. Titles are kept as supplied; check any clipped descriptions. Listed courses are not proof of completion; in-progress, withdrawn, failed, transfer/examination-credit, or ambiguous rows need review. Grades, GPA, and degrees are not imported.')
    return {'courses':courses,'warnings':warnings,'text':text}
