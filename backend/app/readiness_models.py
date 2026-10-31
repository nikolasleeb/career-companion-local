"""Public contracts for account-owned career exploration and readiness."""
from typing import Literal
from pydantic import Field, model_validator
from .models import StrictModel

class Inputs(StrictModel):
    title: str = Field(default='Career exploration', min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=2000)
    interests: str = Field(default='', max_length=2000)
    activities: str = Field(default='', max_length=2000)
    time_available: str = Field(default='', max_length=200)
    preparation_budget: str = Field(default='', max_length=200)
    occupation_codes: list[str] = Field(default_factory=list, max_length=3)
    selected_code: str = Field(default='', max_length=15)
    job_ids: list[str] = Field(default_factory=list, max_length=3)
    salary_area: str = Field(default='US', max_length=40)
    research_enabled: bool = False
    action_budget_usd: float = Field(default=1, ge=.05, le=20, allow_inf_nan=False)

    @model_validator(mode='after')
    def selection(self):
        if len(set(self.occupation_codes)) != len(self.occupation_codes) or len(set(self.job_ids)) != len(self.job_ids):
            raise ValueError('Choose each occupation and posting once.')
        if self.selected_code and self.selected_code not in self.occupation_codes:
            raise ValueError('Choose a direction from the reviewed shortlist.')
        return self

class Update(Inputs):
    expected_revision: int = Field(ge=1)

class Action(StrictModel):
    operation: Literal['discover','compare','assess','follow_up','reassess']
    expected_revision: int = Field(ge=1)
    request_token: str = Field(min_length=8,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    message: str = Field(default='',max_length=5000)
    report_id: str = Field(default='',max_length=64)
    mode: Literal['economy','deep','custom'] = 'economy'

class Reference(StrictModel):
    source_id: str = Field(min_length=1,max_length=160)
    quote: str = Field(min_length=1,max_length=700)

class Finding(StrictModel):
    text: str = Field(min_length=1,max_length=1400)
    references: list[Reference] = Field(default_factory=list,max_length=6)

class Direction(StrictModel):
    code: str = Field(min_length=1,max_length=15)
    interest_connection: Finding
    work_and_preparation: Finding
    strengths: list[Finding] = Field(default_factory=list,max_length=5)
    transferable_experience: list[Finding] = Field(default_factory=list,max_length=5)
    uncertainties: list[str] = Field(default_factory=list,max_length=6)
    tradeoffs: list[Finding] = Field(default_factory=list,max_length=5)
    exploration_activity: str = Field(min_length=1,max_length=1000)

class NextAction(StrictModel):
    title: str = Field(min_length=1,max_length=160)
    purpose: str = Field(min_length=1,max_length=1200)
    effort: str = Field(default='',max_length=200)
    steps: list[str] = Field(min_length=1,max_length=5)
    learning_topics: list[str] = Field(default_factory=list,max_length=5)
    references: list[Reference] = Field(min_length=1,max_length=6)

class Reply(StrictModel):
    outcome: Literal['clarification','shortlist','comparison','assessment','answer']
    summary: str = Field(min_length=1,max_length=5000)
    summary_references: list[Reference] = Field(default_factory=list,max_length=12)
    questions: list[str] = Field(default_factory=list,max_length=3)
    directions: list[Direction] = Field(default_factory=list,max_length=3)
    recommended_code: str = Field(default='',max_length=15)
    recommendation_reason: Finding | None = None
    demonstrated_strengths: list[Finding] = Field(default_factory=list,max_length=8)
    transferable_experience: list[Finding] = Field(default_factory=list,max_length=8)
    needs_clarification: list[str] = Field(default_factory=list,max_length=8)
    development_priorities: list[Finding] = Field(default_factory=list,max_length=8)
    next_actions: list[NextAction] = Field(default_factory=list,max_length=3)
    changes: list[str] = Field(default_factory=list,max_length=8)
    limitations: list[str] = Field(default_factory=list,max_length=8)

class AssessmentReply(Reply):
    outcome: Literal['assessment']
    next_actions: list[NextAction] = Field(min_length=3,max_length=3)

class ConversationReply(Reply):
    outcome: Literal['clarification','shortlist','comparison','answer']

class AgentEnvelope(StrictModel):
    # A nested union keeps the API's root schema an object while enforcing three
    # actions for assessments and allowing clarification without invented actions.
    reply: AssessmentReply | ConversationReply
