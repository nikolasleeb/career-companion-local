"""Optional offer records. Never included in automatic application context."""
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from . import auth, db, explicit_context
from .models import StrictModel
from .resume_conversation import write

router = APIRouter(prefix='/api/applications')

class Details(StrictModel):
    compensation: str = Field(default='', max_length=40)
    currency: str = Field(default='', max_length=3)
    pay_period: Literal['', 'hour', 'week', 'month', 'year', 'other'] = ''
    recurring_bonus: str = Field(default='', max_length=1500)
    signing_bonus: str = Field(default='', max_length=1500)
    equity: str = Field(default='', max_length=2000)
    location: str = Field(default='', max_length=300)
    work_arrangement: Literal['', 'onsite', 'hybrid', 'remote', 'other'] = ''
    start_date: str = Field(default='', max_length=10)
    response_deadline: str = Field(default='', max_length=10)
    benefits: str = Field(default='', max_length=3000)
    notes: str = Field(default='', max_length=4000)

    @field_validator('compensation')
    @classmethod
    def amount(cls, value):
        if value:
            try:
                number = Decimal(value)
                if not number.is_finite() or number < 0 or number > Decimal('1000000000000'):
                    raise ValueError('Enter a nonnegative amount or leave unknown compensation blank.')
            except InvalidOperation:
                raise ValueError('Enter a numeric compensation amount without currency symbols.')
        return value

    @field_validator('currency')
    @classmethod
    def currency_code(cls, value):
        if value and (len(value) != 3 or not value.isascii() or not value.isalpha()):
            raise ValueError('Use a three-letter currency code such as USD.')
        return value.upper()

    @field_validator('start_date', 'response_deadline')
    @classmethod
    def calendar_date(cls, value):
        if value:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError('Use a complete date in YYYY-MM-DD format.')
        return value

class Change(StrictModel):
    expected_revision: int = Field(ge=0)
    details: Details

class Record(StrictModel):
    application_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=1)
    details: Details

def identity(user, application):
    return hashlib.sha256((user + ':offer:' + application).encode()).hexdigest()[:32]

def application(user, id):
    row = db.get(user, id, 'application')
    if not row:
        raise HTTPException(404, 'Application not found.')
    return row

def read(user, id):
    app = application(user, id)
    record = db.get(user, identity(user, id), 'application_offer')
    return {'application': {'id': id, 'title': app['data']['title'], 'company': app['data'].get('company', ''), 'status': app['data']['status']},
            'revision': record['data']['revision'] if record else 0,
            'details': record['data']['details'] if record else Details().model_dump()}

def shared_snapshot(user, id):
    value = read(user, id)
    if not value['revision']:
        raise HTTPException(404, 'Save offer details before sharing them.')
    return {'application_id': id, 'label': value['application']['company'] + ' — ' + value['application']['title'],
            'status': value['application']['status'], 'offer_revision': value['revision'], 'details': value['details']}

@router.get('/{id}/offer')
def get(id: str, user=Depends(auth.current)):
    return read(user['id'], id)

@router.get('/{id}/offer/preview')
def preview(id: str, user=Depends(auth.current)):
    data = shared_snapshot(user['id'], id)
    return {**data, 'context_ref': {'kind': 'offer', 'id': id, 'revision': explicit_context.digest(data)}}

@router.get('/offer-options/list')
def options(user=Depends(auth.current)):
    result = []
    for row in db.list_entities(user['id'], 'application_offer'):
        app = db.get(user['id'], row['data']['application_id'], 'application')
        if app:
            result.append({'application_id': app['id'], 'label': app['data'].get('company', '') + ' — ' + app['data']['title']})
    return {'offers': result}

@router.put('/{id}/offer')
def save(id: str, body: Change, user=Depends(auth.current)):
    uid = user['id']; application(uid, id)
    with db.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        app_row = connection.execute("SELECT payload FROM entities WHERE user_id=? AND id=? AND kind='application'", (uid, id)).fetchone()
        if not app_row:
            raise HTTPException(404, 'Application not found.')
        app_data = json.loads(app_row[0])
        current = connection.execute("SELECT payload FROM entities WHERE user_id=? AND id=? AND kind='application_offer'", (uid, identity(uid, id))).fetchone()
        revision = json.loads(current[0])['revision'] if current else 0
        if revision != body.expected_revision:
            raise HTTPException(409, 'Offer details changed in another window. Load the latest saved offer; your draft is preserved.')
        if not current and app_data['status'] not in ('offer', 'accepted'):
            raise HTTPException(409, 'Save the application status as Offer or Accepted before adding offer details.')
        write(connection, uid, 'application_offer', {'application_id': id, 'revision': revision + 1, 'details': body.details.model_dump()}, identity(uid, id))
    return read(uid, id)

def validate_backup(record, kinds):
    if record['kind'] != 'application_offer':
        return
    value = Record.model_validate(record['data'])
    if kinds.get(value.application_id) != 'application':
        raise ValueError('Offer details need their own application.')
