from typing import Literal, Annotated
from pydantic import BaseModel, Field, ConfigDict, field_validator, SecretStr, model_validator
from urllib.parse import urlparse

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Credentials(StrictModel):
    username: str = Field(min_length=3, max_length=60, pattern=r'^[a-zA-Z0-9_.-]+$')
    password: str = Field(min_length=10, max_length=200)

class SkillItem(StrictModel):
    name: str = Field(min_length=1,max_length=100)
    level: Literal['unknown','beginner','intermediate','advanced'] = 'unknown'

class CertificationItem(StrictModel):
    name: str = Field(min_length=1,max_length=200)
    issuer: str = Field(default='',max_length=200)
    earned_date: str = ''
    valid_from: str = ''
    expiration_date: str = ''
    does_not_expire: bool = False
    credential_id: str = Field(default='',max_length=200)
    credential_url: str = Field(default='',max_length=2000)
    document_id: str = Field(default='',max_length=64)

    @field_validator('credential_url')
    @classmethod
    def credential_link(cls,value): return validate_link(value)

    @field_validator('earned_date','valid_from','expiration_date')
    @classmethod
    def calendar_date(cls,value):
        from datetime import date
        import re
        if value and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value)):
            raise ValueError('Use a complete calendar date or leave it blank.')
        if value: date.fromisoformat(value)
        return value

    @model_validator(mode='after')
    def date_order(self):
        from datetime import date
        if self.earned_date and self.earned_date>date.today().isoformat():
            raise ValueError('Date earned cannot be in the future.')
        if self.does_not_expire and self.expiration_date:
            raise ValueError('Clear the expiration date when Does not expire is selected.')
        if self.expiration_date and self.expiration_date<max(self.earned_date,self.valid_from):
            raise ValueError('Expiration cannot be before the earned or valid-from date.')
        return self

class ExperienceItem(StrictModel):
    certification_items: list[CertificationItem] = Field(default_factory=list,max_length=100)
    skill_items: list[SkillItem] = Field(default_factory=list,max_length=100)
    category: Literal['education','coursework','project','employment','volunteering','skills'] = 'project'
    title: str = Field(min_length=1,max_length=200)
    organization: str = Field(default='',max_length=200)
    dates: str = Field(default='',max_length=120)
    description: str = Field(default='',max_length=12000)
    contribution: str = Field(default='',max_length=6000)
    tools: str = Field(default='',max_length=1000)
    confirmed: bool = False
    source_document_id: str = Field(default='',max_length=64)
    source_entry_id: str = Field(default='',max_length=64)
    location: str = Field(default='',max_length=300)
    degree: str = Field(default='',max_length=150)
    major: str = Field(default='',max_length=200)
    minor: str = Field(default='',max_length=200)
    majors: list[Annotated[str,Field(max_length=200)]] = Field(default_factory=list,max_length=5)
    minors: list[Annotated[str,Field(max_length=200)]] = Field(default_factory=list,max_length=5)
    concentration: str = Field(default='',max_length=200)
    start_date: str = Field(default='',max_length=60)
    end_date: str = Field(default='',max_length=60)
    expected_graduation: str = Field(default='',max_length=60)
    gpa: str = Field(default='',max_length=30)
    gpa_scale: str = Field(default='',max_length=30)
    honors: str = Field(default='',max_length=3000)
    relevant_courses: str = Field(default='',max_length=4000)
    work_arrangement: Literal['','onsite','hybrid','remote'] = ''
    accomplishments: str = Field(default='',max_length=6000)
    project_url: str = Field(default='',max_length=2000)
    project_urls: list[str] = Field(default_factory=list,max_length=5)

    @model_validator(mode='before')
    @classmethod
    def legacy_subjects(cls,value):
        if isinstance(value,dict):
            value=dict(value)
            for field in ('major','minor'):
                if field+'s' not in value:value[field+'s']=[value[field]] if value.get(field) else []
                # Explicit arrays may clear an older compatibility field.
                if isinstance(value[field+'s'],list):value[field]=next((v.strip() for v in value[field+'s'] if isinstance(v,str) and v.strip()),'')
        return value

    @model_validator(mode='after')
    def normalize_subjects(self):
        from .education import subjects
        for field in ('major','minor'):
            values=subjects(self.model_dump(),field)
            setattr(self,field+'s',values);setattr(self,field,values[0] if values else '')
        return self

    @model_validator(mode='after')
    def credential_group(self):
        if self.certification_items and (self.category!='skills' or self.skill_items):
            raise ValueError('Keep certifications in a separate credential group without skill ratings.')
        return self

    @field_validator('project_url')
    @classmethod
    def valid_project_url(cls,value):
        return validate_link(value)

    @field_validator('project_urls')
    @classmethod
    def valid_project_urls(cls,values):
        if any(len(value)>2000 for value in values):raise ValueError('Project links must be at most 2,000 characters.')
        return [validate_link(value.strip()) for value in values if value.strip()]

    @model_validator(mode='after')
    def normalize_project_links(self):
        self.project_urls=project_links(self.model_dump())
        if len(self.project_urls)>5:raise ValueError('Add at most five project links.')
        self.project_url=self.project_urls[0] if self.project_urls else ''
        return self


def validate_link(value):
    if value:
        try:
            parsed=urlparse(value)
            if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password: raise ValueError()
            parsed.port
        except ValueError: raise ValueError('Enter a complete http:// or https:// link without credentials.') from None
    return value

def project_links(data):
    links=[];seen=set()
    for value in [data.get('project_url') or '',*(data.get('project_urls') or [])]:
        value=value.strip();key=value.rstrip('/')
        if value and key not in seen:links.append(value);seen.add(key)
    return links

class JobPosting(StrictModel):
    title: str = Field(default='Target opportunity',max_length=250)
    company: str = Field(default='',max_length=250)
    description: str = Field(min_length=10,max_length=100000)
    url: str = Field(default='',max_length=2000)

class AnalysisRequest(StrictModel):
    job_id: str
    mode: Literal['economy','deep','custom'] = 'economy'
    request_token: str = Field(default='',max_length=100)

class Evidence(StrictModel):
    record_id: str
    quote: str

class Requirement(StrictModel):
    keyword: str
    job_quote: str
    importance: Literal['required','preferred','unclear']
    status: Literal['supported','wording_opportunity','no_evidence','needs_confirmation']
    evidence: list[Evidence]
    explanation: str
    question: str

class Suggestion(StrictModel):
    record_id: str
    original: str
    proposed: str
    reason: str
    guide_id: str
    guide_quote: str

class AnalysisOutput(StrictModel):
    summary: str
    requirements: list[Requirement]
    suggestions: list[Suggestion]
    questions: list[str]

class Decision(StrictModel):
    index: int = Field(ge=0)
    action: Literal['accept','edit','reject']
    text: str = Field(default='',max_length=6000)

class ResumeRequest(StrictModel):
    compact_skills: bool = True
    draft_id: str | None = None
    headline: str | None = Field(default=None,max_length=250)
    overrides: dict[str,str] = Field(default_factory=dict,max_length=1000)

    job_id: str | None = None
    content: dict[str, list[int]] | None = None
    recommend: bool = False
    title: str = Field(default='Tailored resume',min_length=1,max_length=900)
    template: Literal['education','experience'] = 'education'
    experience_ids: list[str] = Field(default_factory=list,max_length=100)
    analysis_id: str | None = None
    decisions: list[Decision] = Field(default_factory=list,max_length=100)

class OpenAIKeyUpdate(StrictModel):
    api_key: SecretStr

    @field_validator('api_key')
    @classmethod
    def valid_key(cls,value):
        import re
        key=value.get_secret_value().strip()
        if not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,500}',key):
            raise ValueError('Enter a complete OpenAI API key beginning with sk-.')
        return SecretStr(key)

class SettingsUpdate(StrictModel):
    us_citizen: Literal["", "yes", "no", "unsure"] | None = None
    authorized_us: Literal["", "yes", "no", "unsure"] | None = None
    sponsorship_now: Literal["", "yes", "no", "unsure"] | None = None
    sponsorship_future: Literal["", "yes", "no", "unsure"] | None = None
    custom_model: Literal['gpt-6.1-sol','gpt-6-luna','gpt-5.6-sol','gpt-5.6-luna','gpt-5.6-terra'] | None = None
    custom_reasoning: Literal['none','low','medium','high','xhigh','max'] | None = None
    custom_speed: Literal['standard','fast','ultrafast'] | None = None
    mode: Literal['economy','deep','custom'] | None = None
    name: str | None = Field(default=None,max_length=150)
    contact: str | None = Field(default=None,max_length=500)
    contact_reviewed: bool | None = None
    headline: str | None = Field(default=None,max_length=250)
    email: str | None = Field(default=None,max_length=254,pattern=r'^(?:[^@\s]+@[^@\s]+\.[^@\s]+)?$')
    phone: str | None = Field(default=None,max_length=80)
    city: str | None = Field(default=None,max_length=150)
    state: str | None = Field(default=None,max_length=150)
    country: str | None = Field(default=None,max_length=150)
    county: str | None = Field(default=None,max_length=150)
    website: str | None = Field(default=None,max_length=2000)
    linkedin: str | None = Field(default=None,max_length=2000)

    @model_validator(mode='after')
    def model_effort_compatible(self):
        if self.custom_model and (self.custom_reasoning or self.custom_speed):
            from .ai_settings import validate_custom
            validate_custom(self.model_dump(exclude_none=True))
        return self

    @field_validator('website','linkedin')
    @classmethod
    def valid_profile_link(cls,value):
        return validate_link(value) if value is not None else None

class AnswerRequest(StrictModel):
    question: str = Field(min_length=5,max_length=2000)
    answer: str = Field(min_length=5,max_length=12000)
    job_id: str
    mode: Literal['economy','deep','custom'] = 'economy'
    session_id: str | None = None

class InterviewOutput(StrictModel):
    strengths: list[str]
    improvements: list[str]
    evidence: list[Evidence]
    follow_up: str

class PrepRequest(StrictModel):
    job_id: str
    analysis_id: str | None = None
    confirmed_gaps: list[str] = Field(default_factory=list,max_length=30)
    mode: Literal['economy','deep','custom'] = 'economy'

class PrepOutput(StrictModel):
    priorities: list[str]
    resource_ids: list[str]
    questions: list[str]

class Board(StrictModel):
    provider: Literal['greenhouse','ashby','lever'] = 'greenhouse'
    board: str = Field(default='',max_length=100,pattern=r'^[A-Za-z0-9_-]*$')
    company: str = Field(min_length=1,max_length=150)
    career_url: str = Field(default='',max_length=2000)
    region: Literal['global','eu'] = 'global'

    @model_validator(mode='before')
    @classmethod
    def from_career_url(cls,value):
        if isinstance(value,dict) and value.get('career_url'):
            from urllib.parse import urlparse
            p=urlparse(value['career_url']);host=(p.hostname or '').lower()
            providers={'boards.greenhouse.io':'greenhouse','job-boards.greenhouse.io':'greenhouse','jobs.ashbyhq.com':'ashby','jobs.lever.co':'lever','jobs.eu.lever.co':'lever'}
            if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or host not in providers:raise ValueError('Use a public Greenhouse, Ashby or Lever HTTPS career-page URL.')
            token=p.path.strip('/').split('/')[0]
            value={**value,'provider':providers[host],'board':token,'region':'eu' if host=='jobs.eu.lever.co' else 'global'}
        if isinstance(value,dict) and not value.get('board'):raise ValueError('Enter an employer career-page URL or board name.')
        return value

class SearchRequest(StrictModel):
    title: str = Field(default='data analyst',min_length=2,max_length=120)
    interests: list[str] = Field(default_factory=list,max_length=12)
    location: str = Field(default='United States',min_length=2,max_length=120)
    workplace: Literal['any','remote','hybrid','onsite'] = 'any'
    job_types: list[Literal['internship','early_career','mid_career','any']] = Field(default_factory=lambda:['internship','early_career'],min_length=1,max_length=3)
    career_levels: list[Literal['internship','early_career','mid_career']] | None = Field(default=None,min_length=1,max_length=3)
    locations: list[Annotated[str,Field(min_length=2,max_length=120)]] = Field(default_factory=list,max_length=10)
    minimum_salary: float | None = Field(default=None,ge=0,le=10000000)
    pay_period: Literal['year','hour'] = 'year'
    days: int = Field(default=30,ge=1,le=30)
    mode: Literal['economy','deep','custom'] = 'economy'
    refresh: bool = False
    sources: list[Literal['greenhouse','ashby','lever','web','adzuna','usajobs','jobspy','github']] = Field(default_factory=lambda:['greenhouse','ashby','lever','adzuna','usajobs','github'],max_length=8)
    trial_roles: list[str] | None = Field(default=None,max_length=2)
    employer_boards: list[str] | None = Field(default=None,max_length=300)
    request_token: str = Field(default='',max_length=100,pattern=r'^[a-zA-Z0-9_-]*$')

    @field_validator('interests','trial_roles')
    @classmethod
    def valid_interests(cls,values):
        if values is None:return None
        if any(not isinstance(v,str) or not 2<=len(v.strip())<=80 for v in values):raise ValueError('Use interests between 2 and 80 characters.')
        return list(dict.fromkeys(v.strip() for v in values))

class WebJob(StrictModel):
    title: str
    company: str
    description: str
    url: str

class WebJobsOutput(StrictModel):
    jobs: list[WebJob]

class ImportURL(StrictModel):
    url: str = Field(min_length=8,max_length=2000)

class AssessmentProgress(StrictModel):
    answers: dict[str,int] = Field(default_factory=dict,max_length=30)
    job_zone: int | None = Field(default=None,ge=1,le=5)

class PasswordChange(StrictModel):
    current: str = Field(max_length=200)
    password: str = Field(min_length=10,max_length=200)


class ResumeImportEntry(StrictModel):
    id: str = Field(min_length=1,max_length=64)
    data: ExperienceItem

class ResumeImportApproval(StrictModel):
    text_hash: str = Field(min_length=64,max_length=64)
    profile_updates: SettingsUpdate = Field(default_factory=SettingsUpdate)
    entries: list[ResumeImportEntry] = Field(default_factory=list,max_length=100)
    reviewed: Literal[True]

# New comparisons are explicit about qualifications, eligibility, and logistics.
class ComparisonRequirement(StrictModel):
    criterion_id: str = ""
    keyword: str
    job_quote: str
    kind: Literal['qualification','eligibility']
    importance: Literal['required','preferred','unclear']
    status: Literal['supported','partial','unknown','not_met']
    evidence: list[Evidence]
    explanation: str
    question: str

class DutyAssessment(ComparisonRequirement):
    kind: Literal['responsibility'] = 'responsibility'
    importance: Literal['unclear'] = 'unclear'

class PostingDetail(StrictModel):
    field: Literal['location','onsite','hours','schedule','dates']
    value: str
    job_quote: str

class ContentRecommendation(StrictModel):
    record_id: str
    reason: str
    evidence: list[Evidence]

class ComparisonKeyword(StrictModel):
    term: str
    job_quote: str
    evidence: list[Evidence]

class ComparisonOutput(StrictModel):
    duty_assessments: list[DutyAssessment] = Field(default_factory=list,max_length=80)
    keywords: list[ComparisonKeyword] = Field(default_factory=list)
    summary: str
    requirements: list[ComparisonRequirement]
    job_details: list[PostingDetail]
    recommendations: list[ContentRecommendation]
    suggestions: list[Suggestion]
    questions: list[str]

class CatalogEvidence(StrictModel):
    """A reference to one exact, account-scoped passage supplied by the server."""
    source_id: str = Field(min_length=1,max_length=80)

class CriterionAssessment(StrictModel):
    """AI assesses an existing posting criterion; the server owns its wording/source."""
    criterion_id: str = Field(min_length=1,max_length=64)
    status: Literal['supported','partial','unknown','not_met']
    evidence: list[CatalogEvidence]
    explanation: str
    question: str
    project_context_ids: list[str] = Field(default_factory=list,max_length=5)

class CatalogRecommendation(ContentRecommendation):
    evidence: list[CatalogEvidence]

class CatalogKeyword(ComparisonKeyword):
    evidence: list[CatalogEvidence]

class CatalogSuggestion(StrictModel):
    source_id: str = Field(min_length=1,max_length=80)
    guidance_source_id: str = Field(min_length=1,max_length=80)
    proposed: str
    reason: str

class CatalogComparisonOutput(ComparisonOutput):
    requirements: list[CriterionAssessment]
    duty_assessments: list[CriterionAssessment] = Field(default_factory=list,max_length=80)
    recommendations: list[CatalogRecommendation]
    keywords: list[CatalogKeyword] = Field(default_factory=list)
    suggestions: list[CatalogSuggestion]


ApplicationStatus = Literal['preparing','applied','screening','interviewing','offer','accepted','rejected','withdrawn','declined']
class ApplicationEvent(StrictModel):
    status: ApplicationStatus
    date: str = ''
    note: str = Field(default='',max_length=3000)

    @field_validator('date')
    @classmethod
    def valid_date(cls,value):
        if value:
            from datetime import date
            try:
                if date.fromisoformat(value).isoformat()!=value: raise ValueError()
            except ValueError: raise ValueError('Use YYYY-MM-DD or leave the date blank.') from None
        return value

class InterviewRound(StrictModel):
    date: str = ''
    type: str = Field(default='',max_length=150)
    outcome: str = Field(default='',max_length=1000)
    _date = field_validator('date')(classmethod(lambda cls,v: ApplicationEvent.valid_date(v)))

class ApplicationAttachment(StrictModel):
    kind:Literal['cover_letter','document']='cover_letter'
    record_id:str=Field(min_length=1,max_length=64)

class ApplicationInput(StrictModel):
    job_id: str = ''
    title: str = Field(min_length=1,max_length=250)
    company: str = Field(default='',max_length=250)
    url: str = Field(default='',max_length=2000)
    posting_snapshot: dict = Field(default_factory=dict)
    resume_ids: list[str] = Field(default_factory=list,max_length=100)
    submitted_resume_id: str = ''
    status: ApplicationStatus = 'preparing'
    applied_date: str = ''
    history: list[ApplicationEvent] = Field(default_factory=list,max_length=200)
    interviews: list[InterviewRound] = Field(default_factory=list,max_length=100)
    notes: str = Field(default='',max_length=12000)
    archived: bool = False
    attachments: list[ApplicationAttachment] = Field(default_factory=list,max_length=100)
    workflow: dict = Field(default_factory=dict)
    _date = field_validator('applied_date')(classmethod(lambda cls,v: ApplicationEvent.valid_date(v)))


class DraftItem(StrictModel):
    item_id: str
    text: str = Field(min_length=1,max_length=1800)
    reason: str
    priority: int = Field(ge=1,le=100)

class DraftEntry(StrictModel):
    record_id: str
    reason: str
    items: list[DraftItem]

class DraftKeyword(StrictModel):
    term: str = Field(min_length=1,max_length=100)
    job_quote: str
    evidence: list[Evidence]

class DraftOmission(StrictModel):
    record_id: str
    reason: str

class OptimizationOutput(StrictModel):
    omissions: list[DraftOmission] = Field(default_factory=list)
    headline: str = Field(max_length=250)
    headline_evidence: list[Evidence]
    entries: list[DraftEntry]
    keywords: list[DraftKeyword]

class DraftAudit(StrictModel):
    approved: bool
    issues: list[str]

class OptimizationRequest(ResumeRequest):
    mode: Literal['economy','deep','custom'] = 'economy'

# Guided resume sessions keep user facts separate from writing instructions.
class FactField(StrictModel):
    field: str
    value: str = Field(max_length=12000)
    user_quote: str = Field(min_length=1,max_length=12000)
    suggested_value: str = Field(default='',max_length=12000)

class FactProposalOutput(StrictModel):
    record_id: str
    category: Literal['education','employment','project','volunteering','skills','coursework','authorization']
    title: str = Field(max_length=200)
    fields: list[FactField] = Field(max_length=20)
    reason: str
    criterion_ids: list[str]
    editing_note: str = Field(default='',max_length=600)
    improvement_suggestions:list[str]=Field(default_factory=list,max_length=3)

class ProjectFollowup(StrictModel):
    text: str = Field(min_length=5,max_length=1000)
    project_context_ids: list[str] = Field(min_length=1,max_length=5)


class ResumeChatOutput(StrictModel):
    message: str
    questions: list[str] = Field(max_length=3)
    proposals: list[FactProposalOutput] = Field(max_length=8)
    action: Literal['question','facts','revise']
    revision_instruction: str
    target_item_ids: list[str]
    target_record_ids: list[str]
    change_headline: bool
    change_selection: bool
    project_questions: list[ProjectFollowup] = Field(default_factory=list,max_length=3)


class ConversationStart(StrictModel):
    job_id: str
    analysis_id: str | None = None

class ConversationMessage(StrictModel):
    question_answers:list[dict]=Field(default_factory=list,max_length=30)
    text: str = Field(min_length=1,max_length=12000)
    mode: Literal['economy','deep','custom'] = 'economy'
    expected_version: int = Field(ge=0)

class FactApproval(StrictModel):
    proposal_id: str
    expected_version: int = Field(ge=0)
    action: Literal['approve','reject']
    values: dict[str,str] = Field(default_factory=dict,max_length=20)
    title: str | None = Field(default=None,max_length=200)
    update_draft: bool = True
    mode: Literal['economy','deep','custom'] = 'economy'
    evidence_experience_id: str = Field(default='',max_length=64)
    evidence_expected_updated_at: str = Field(default='',max_length=100)
    keep_standalone: bool = False

class GuidedBuild(StrictModel):
    preparation: ResumeRequest | None = None
    expected_version: int = Field(ge=0)
    mode: Literal['economy','deep','custom'] = 'economy'
    decisions: list[Decision] = Field(default_factory=list,max_length=100)
    template: Literal['education','experience'] = 'education'

class WorkingRender(StrictModel):
    expected_version: int = Field(ge=0)
    request_token: str = Field(min_length=1,max_length=100)
    resume: ResumeRequest

class RevisionAction(StrictModel):
    revision_id: str
    expected_version: int = Field(ge=0)

class FinalizeRevision(RevisionAction):
    reviewed: Literal[True]

class LegacyDraftLoad(StrictModel):
    expected_version:int=Field(ge=0)
    draft_id:str

class CoverEvidence(StrictModel):
    source_id:str
    quote:str=Field(min_length=1,max_length=3000)

class CoverParagraph(StrictModel):
    text:str=Field(min_length=1,max_length=2500)
    evidence:list[CoverEvidence]=Field(min_length=1,max_length=12)

class CoverLetterOutput(StrictModel):
    paragraphs:list[CoverParagraph]=Field(min_length=2,max_length=5)
    summary:str=Field(max_length=500)

class CoverContent(StrictModel):
    header_style:Literal['compact','full']='compact'
    show_subject:bool=False
    letter_date:str=''
    subject:str=Field(default='',max_length=400)
    greeting:str=Field(default='Dear Hiring Manager,',min_length=1,max_length=180)
    paragraphs:list[str]=Field(default_factory=lambda:[''],min_length=1,max_length=8)
    closing:str=Field(default='Sincerely,',min_length=1,max_length=100)
    _date=field_validator('letter_date')(classmethod(lambda cls,v:ApplicationEvent.valid_date(v)))

    @field_validator('paragraphs')
    @classmethod
    def paragraph_limits(cls,value):
        if any(len(p)>3000 for p in value) or sum(map(len,value))>12000:raise ValueError('Keep each paragraph under 3,000 characters and the letter under 12,000.')
        return value

class CoverStart(StrictModel):
    job_id:str
    resume_id:str
    letter_date:str=''
    _date=field_validator('letter_date')(classmethod(lambda cls,v:ApplicationEvent.valid_date(v)))

class CoverEdit(StrictModel):
    expected_version:int=Field(ge=0)
    content:CoverContent
    instructions:str=Field(default='',max_length=3000)
    request_token:str=Field(default='',max_length=100)

class CoverGenerate(CoverEdit):
    skip_questions:bool=False
    mode:Literal['economy','deep','custom']='economy'

class CoverMessage(CoverGenerate):
    polish_proposal_ids:list[str]=Field(default_factory=list,max_length=6)
    question_answers:list[dict]=Field(default_factory=list,max_length=30)
    text:str=Field(min_length=1,max_length=12000)

class CoverChatOutput(StrictModel):
    details:list['CoverDetailOutput']=Field(default_factory=list,max_length=6)
    answered_question_ids:list[str]=Field(default_factory=list,max_length=12)
    skipped_question_ids:list[str]=Field(default_factory=list,max_length=12)
    followup_questions:list['CoverQuestionOutput']=Field(default_factory=list,max_length=2)
    action:Literal['reply','revise','collect']
    reply:str=Field(min_length=1,max_length=1800)
    revision_instruction:str=Field(default='',max_length=3000)
    paragraph_indices:list[int]=Field(default_factory=list,max_length=8)
    revise_all:bool=False
    header_style:Literal['unchanged','compact','full']='unchanged'
    subject:Literal['unchanged','show','hide']='unchanged'

class CoverQuestionOutput(StrictModel):
    text:str=Field(min_length=5,max_length=500)
    purpose:str=Field(min_length=5,max_length=600)
    topic:Literal['motivation','story','contribution']
    source_ids:list[str]=Field(default_factory=list,max_length=6)
    job_quote:str=Field(default='',max_length=1200)
    guidance_ids:list[str]=Field(default_factory=list,max_length=4)
    project_context_ids:list[str]=Field(default_factory=list,max_length=5)

class CoverQuestionsOutput(StrictModel):
    message:str=Field(min_length=1,max_length=1200)
    questions:list[CoverQuestionOutput]=Field(max_length=3)

class CoverDetailOutput(StrictModel):
    kind:Literal['motivation','experience']
    user_quote:str=Field(min_length=1,max_length=3000)
    title:str=Field(min_length=1,max_length=180)
    question_ids:list[str]=Field(default_factory=list,max_length=6)
    related_source_id:str=''
    supersedes_id:str=''
    profile_category:Literal['project','employment','education','volunteering']='project'
    suggested_text:str=Field(default='',min_length=1,max_length=3000)
    editing_note:str=Field(default='',min_length=1,max_length=600)
    improvement_suggestions:list[str]=Field(default_factory=list,max_length=3)

class CoverPolishedDetail(StrictModel):
    proposal_id:str
    suggested_text:str=Field(min_length=1,max_length=3000)
    editing_note:str=Field(min_length=1,max_length=600)
    improvement_suggestions:list[str]=Field(default_factory=list,max_length=3)

class CoverPolishOutput(StrictModel):
    details:list[CoverPolishedDetail]=Field(min_length=1,max_length=6)

class CoverReviewDecision(StrictModel):
    proposal_id:str
    action:Literal['approve','reject']
    text:str=Field(default='',max_length=3000)
    save_to_profile:bool=False
    profile_record_id:str=''
    profile_expected_updated_at:str=''
    profile_title:str=Field(default='',max_length=180)
    profile_category:Literal['project','employment','education','volunteering']='project'
    evidence_experience_id:str=Field(default='',max_length=64)
    evidence_expected_updated_at:str=Field(default='',max_length=100)
    keep_standalone:bool=False
    experience_ids:list[str] | None=Field(default=None,max_length=10)

class CoverContextReview(CoverGenerate):
    decisions:list[CoverReviewDecision]=Field(min_length=1,max_length=12)
    build:bool=True

class CoverQuestionSkip(StrictModel):
    expected_version:int=Field(ge=0)
    question_ids:list[str]=Field(min_length=1,max_length=30)

CoverChatOutput.model_rebuild()

class InlineAnswer(StrictModel):
    expected_answer_version:int | None=Field(default=None,ge=0)
    question_id:str=Field(min_length=1,max_length=100)
    text:str=Field(default='',max_length=6000)
    skipped:bool=False

class AnswerDraftSave(StrictModel):
    expected_version:int=Field(ge=0)
    answers:list[InlineAnswer]=Field(min_length=1,max_length=30)

class AnswerBatchReview(StrictModel):
    expected_version:int=Field(ge=0)
    question_ids:list[str]=Field(min_length=1,max_length=30)
    mode:Literal['economy','deep','custom']='economy'
    request_token:str=Field(default='',max_length=100)

class ProfileAnswerEdit(StrictModel):
    expected_version:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=200)
    text:str=Field(min_length=1,max_length=12000)
    experience_id:str=''
    experience_ids:list[str] | None=Field(default=None,max_length=10)
    experience_updated_at:str=''
    values:dict[str,str]=Field(default_factory=dict,max_length=20)
    archived:bool=False

class ApplicationWorkflow(StrictModel):
    step:Literal['resume','cover','agent']='resume'
    resume_id:str=''
    cover_letter_id:str=''
    cover_skipped:bool=False

class ApplicationStart(StrictModel):
    job_id:str

class ApplicationWorkflowUpdate(StrictModel):
    expected_updated_at:str
    workflow:ApplicationWorkflow

class CoverSourceSelection(StrictModel):
    expected_version:int=Field(ge=0)
    answer_ids:list[str]=Field(default_factory=list,max_length=100)

class ProfileDraftReview(StrictModel):
    builder:Literal['resume','cover']
    conversation_id:str
    question_id:str
    expected_answer_version:int=Field(ge=1)
    title:str=Field(min_length=1,max_length=200)
    text:str=Field(min_length=1,max_length=6000)
    answer_kind:Literal['experience','motivation']='experience'
    experience_id:str=''
    experience_ids:list[str] | None=Field(default=None,max_length=10)
    category:Literal['education','employment','project','volunteering','skills','coursework']='project'
