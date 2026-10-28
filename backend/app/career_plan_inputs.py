"""Optional planning inputs and editable proposed milestones, separate from qualifications."""
from datetime import date
from typing import Annotated, Literal
from fastapi import HTTPException
from pydantic import Field, field_validator
from .models import StrictModel

class PlanInput(StrictModel):
    purpose: Literal['explore', 'internships', 'graduation', 'career_change', 'certification', 'custom'] = 'custom'
    objective: str = Field(min_length=1, max_length=2000)
    target: str = Field(default='', max_length=150)
    time_available: str = Field(default='', max_length=200)
    budget: str = Field(default='', max_length=200)
    goal_ids: list[str] = Field(default_factory=list, max_length=5)
    goals_revision: int = Field(default=0, ge=0)

class MilestoneEdit(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=160)
    steps: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(min_length=1, max_length=5)
    period_label: str = Field(default='', max_length=100)
    due_date: str = Field(default='', max_length=10)
    effort: str = Field(default='', max_length=250)

    @field_validator('due_date')
    @classmethod
    def actual_date(cls, value):
        if value and date.fromisoformat(value).isoformat() != value:
            raise ValueError('Use YYYY-MM-DD or leave the date blank.')
        return value

def context(user, plan):
    if plan is None:
        return None
    from . import career_goals
    current = career_goals.read(user)
    if plan.goal_ids and plan.goals_revision != current['revision']:
        raise HTTPException(409, 'Career Goals changed. Refresh your plan inputs and review the selected goals; your draft is preserved.')
    catalog = {g['id']: g for g in current['items']}
    if any(g not in catalog for g in plan.goal_ids):
        raise HTTPException(404, 'A selected planning goal is no longer available.')
    return {**plan.model_dump(), 'selected_goals_as_aspirations': [catalog[g] for g in dict.fromkeys(plan.goal_ids)]}

def date_supported(value, citations):
    if not value:
        return False
    chosen = date.fromisoformat(value)
    forms = {chosen.isoformat(), chosen.strftime('%B ') + str(chosen.day) + chosen.strftime(', %Y'),
             chosen.strftime('%b ') + str(chosen.day) + chosen.strftime(', %Y')}
    text = ' '.join(c.get('quote', '') for c in citations if c.get('kind') == 'fetched' and not c.get('stale'))
    text = ' '.join(text.casefold().split())
    return any(form.casefold() in text for form in forms)
