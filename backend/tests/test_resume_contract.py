"""Provider format rejects attribution errors before a draft can be materialized."""
import asyncio,copy,json
import pytest
from pydantic import ValidationError
from app import ai,resume_contract
from app.network import ServiceError


def evidence():
    records=[{'record_id':v,'title':v,'category':'employment' if v=='job' else 'project'} for v in ('job','project','other')]
    def fact(id,origin,field='description',destinations=None):
        return {'id':id,'record_id':origin,'field':field,'allowed_destinations':destinations or [origin]}
    return {'records':records,'facts':[
        fact('F1','job'),fact('F2','project',destinations=['project','job']),
        fact('F3','project',destinations=['project','job']),fact('F4','project','tools'),
        fact('F5','other'),fact('F6','project'),fact('F7','project','header'),fact('F8','project','tools')]}


def draft(ids=('F2','F3'),destination='job'):
    return {'headline':'','headline_evidence':[],'entries':[{'record_id':destination,'reason':'Relevant work','items':[
        {'source_ids':list(ids),'text':'A supported contribution.','priority':80,'reason':'Relevant work'}]}],'omissions':[],'keywords':[]}


def test_linked_project_and_job_can_share_entry_with_separate_bullets():
    schema=resume_contract.composition_schema(evidence());value=draft()
    value['entries'][0]['items'].append({**value['entries'][0]['items'][0],'source_ids':['F1']})
    assert schema.model_validate(value).model_dump()==value
    assert schema.model_validate(draft(['F2','F6'],'project')) # Differing placement permissions remain available at their owner.


@pytest.mark.parametrize('ids,destination',[
    (['F1','F2'],'job'),(['F2','F5'],'job'),(['F2','F4'],'project'),
    (['F4','F8'],'project'),(['F4'],'job'),(['F6'],'job'),
    (['F7'],'project'),(['other-account-fact'],'project'),(['F2'],'other')])
def test_incompatible_evidence_is_not_expressible(ids,destination):
    with pytest.raises(ValidationError):resume_contract.composition_schema(evidence()).model_validate(draft(ids,destination))


def test_fact_groups_preserve_owner_and_do_not_mutate_catalog():
    source=evidence();before=copy.deepcopy(source);groups=resume_contract.groups(source)
    assert source==before
    project=next(g for g in groups if g['original_experience_id']=='project')
    assert project['narrative_source_ids']==['F2','F3','F6']
    assert project['separate_qualification_source_ids']==['F4','F8']


def test_schema_applies_individual_permissions_without_forbidding_compatible_owner_facts():
    # All facts in a branch share both the owner and its placement permissions.
    schema=resume_contract.composition_schema(evidence())
    assert schema.model_validate(draft(['F6'],'project'))
    with pytest.raises(ValidationError):schema.model_validate(draft(['F6','F2'],'job'))


def test_large_catalog_uses_finite_patterns_instead_of_exceeding_enum_limit():
    source=evidence();source['facts']=[{'id':'F'+str(n),'record_id':'project','field':'description','allowed_destinations':['project']} for n in range(1001)]
    schema=resume_contract.composition_schema(source);raw=schema.model_json_schema()
    assert 'pattern' in json.dumps(raw)
    assert schema.model_validate(draft(['F1000'],'project'))
    with pytest.raises(ValidationError):schema.model_validate(draft(['F1001'],'project'))


def test_provider_receives_nested_schema_and_malformed_reply_is_not_retried(monkeypatch):
    calls=[]
    async def respond(body,retry_allowed=True):
        calls.append(body);assert retry_allowed is False
        shape=body['text']['format']['schema']
        assert shape['type']=='object' and 'anyOf' not in shape
        def objects(node):
            if isinstance(node,dict):
                if node.get('type')=='object':
                    assert node['additionalProperties'] is False
                    assert set(node['required'])==set(node['properties'])
                for v in node.values():objects(v)
            elif isinstance(node,list):
                for v in node:objects(v)
        objects(shape)
        return {'output':[{'content':[{'type':'output_text','text':json.dumps(draft(['F1','F2']))}]}]}
    monkeypatch.setattr(ai,'call_api',respond)
    with pytest.raises(ServiceError,match='output contract'):
        asyncio.run(ai.structured(resume_contract.composition_schema(evidence()),{},retry_allowed=False))
    assert len(calls)==1
