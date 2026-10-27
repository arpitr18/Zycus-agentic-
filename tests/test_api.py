"""Isolated application contract tests; injected agents never enter real history."""
import copy
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from api.main import create_app
from api.db import User,SessionRecord,Investigation,Assignment
from tam_agent.schema import EXAMPLE

def test_agent(ticket,ctx):
    result=copy.deepcopy(EXAMPLE)
    result.update(ticket_id=ticket['ticket_id'],account_id=ticket['resolved_account_id'],kb_references=['KB-2914'],
        customer_reply='Please provide the affected module and exact error.',internal_note='Isolated API test fixture.',
        category='needs_info',needs_clarification=True)
    ctx.llm.calls=1
    ctx.llm.record({'event':'llm','usage':{'prompt_tokens':100,'completion_tokens':50}})
    ctx.audit_sink({'step':1,'action':'test_fixture','input':'{}','observation':'Isolated fixture'}, {'tool':'test_fixture','seconds':.01})
    return result
test_agent.__test__=False

@pytest.fixture
def client(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'test.db'),demo=True,agent=test_agent)
    with TestClient(app) as client: yield client

def login(client,role='admin'):
    result=client.post('/api/auth/login',json={'email':role+'@demo.local','password':'Demo@1234'})
    assert result.status_code==200,result.text
    return {'X-CSRF-Token':result.json()['csrf_token']}

def wait(client,rid):
    for _ in range(100):
        result=client.get('/api/investigations/'+rid).json()
        if result.get('status') in ('succeeded','failed'): return result
        time.sleep(.02)
    raise AssertionError('Test job did not finish')

def test_auth_cookie_csrf_and_revocation(client):
    assert client.get('/api/tickets').status_code==401
    assert client.post('/api/auth/login',json={'email':'admin@demo.local','password':'bad'}).status_code==401
    headers=login(client)
    cookie=client.cookies.get('zycus_session')
    with client.app.state.factory() as db:
        assert not db.get(SessionRecord,cookie)
        assert db.scalar(select(User)).password_hash.startswith('scrypt$')
    assert client.post('/api/auth/logout').status_code==403
    assert client.post('/api/auth/logout',headers={**headers,'Origin':'https://evil.invalid'}).status_code==403
    assert client.post('/api/auth/logout',headers=headers).status_code==200
    assert client.get('/api/auth/me').status_code==401

def test_role_scope_and_direct_object_access(client):
    headers=login(client,'support')
    assert client.get('/api/users').status_code==403
    assert client.get('/api/analytics').status_code==403
    assert client.get('/api/settings').status_code==403
    allowed=set(client.get('/api/auth/me').json()['user']['account_ids'])
    rows=client.get('/api/tickets?page_size=100').json()
    assert all(t['resolved_account_id'] in allowed for t in rows['items'])
    foreign=next(t for t in client.app.state.store.tickets.values() if t['resolved_account_id'] not in allowed)
    assert client.get('/api/tickets/'+foreign['ticket_id']).status_code==404
    assert client.get('/api/accounts/'+foreign['resolved_account_id']).status_code==404
    assert client.post('/api/investigations',json={'ticket_id':foreign['ticket_id']},headers=headers).status_code==404
    assert client.get('/api/kb/KB-2914').status_code==200
    assert client.post('/api/investigations/cli-TKT-128253/reviews',json={'state':'approved','note':'good'},headers=headers).status_code==403

def test_investigate_review_and_real_metrics_pipeline(client):
    headers=login(client)
    rates={'openai/gpt-oss-20b':{'input_per_million':2,'output_per_million':4,'source':'Test-only controlled fixture rates'}}
    model=client.get('/api/settings').json()['model']
    rates={model:next(iter(rates.values()))}
    assert client.put('/api/settings/pricing',json=rates,headers=headers).status_code==200
    response=client.post('/api/investigations',json={'ticket_id':'TKT-128253'},headers=headers)
    assert response.status_code==202,response.text
    run=wait(client,response.json()['id'])
    assert run['status']=='succeeded',run
    assert run['result']['ticket_id']=='TKT-128253'
    assert run['input_tokens']==100 and run['output_tokens']==50
    assert run['estimated_cost_usd']==pytest.approx(.0004)
    assert run['events']
    before=copy.deepcopy(run['result'])
    review=client.post('/api/investigations/'+run['id']+'/reviews',headers=headers,json={'state':'amended','note':'Verified additional business impact.','priority':'P2'})
    assert review.status_code==200,review.text
    after=client.get('/api/investigations/'+run['id']).json()
    assert after['result']==before and after['reviews'][0]['overrides']=={'priority':'P2'}
    analytics=client.get('/api/analytics').json()
    assert analytics['input_tokens']>=100 and analytics['priced_run_count']>=1
    assert client.get('/api/audit').json()['total']>0

def test_invalid_agent_output_fails_and_is_persisted(client):
    headers=login(client)
    client.app.state.jobs.agent=lambda ticket,ctx:{'ticket_id':ticket['ticket_id']}
    response=client.post('/api/investigations',headers=headers,json={'ticket_id':'TKT-128253'})
    run=wait(client,response.json()['id'])
    assert run['status']=='failed' and run['result'] is None
    assert 'invalid schema' in run['error']

def test_users_assignment_and_last_admin_protection(client):
    headers=login(client)
    me=client.get('/api/auth/me').json()['user']
    payload={'email':me['email'],'name':me['name'],'role':'support','active':True,'account_ids':[]}
    assert client.put('/api/users/'+str(me['id']),json=payload,headers=headers).status_code==409
    payload={'email':'new@demo.local','name':'New Support','role':'support','password':'StrongPassword@123','account_ids':['ACC-6031']}
    result=client.post('/api/users',json=payload,headers=headers)
    assert result.status_code==201,result.text
    assert result.json()['account_ids']==['ACC-6031']
    assert 'password_hash' not in result.text
    payload['account_ids']=['ACC-NOT-REAL'];payload['email']='other@demo.local'
    assert client.post('/api/users',json=payload,headers=headers).status_code==422

def test_filters_pagination_and_kb(client):
    login(client,'manager')
    result=client.get('/api/tickets?q=TKT-128253').json()
    assert result['total']==1 and result['items'][0]['ticket_id']=='TKT-128253'
    first=client.get('/api/tickets?page=1&page_size=5').json()
    second=client.get('/api/tickets?page=2&page_size=5').json()
    assert not ({x['ticket_id'] for x in first['items']}&{x['ticket_id'] for x in second['items']})
    assert client.get('/api/tickets?page_size=1000').status_code==422
    assert client.get('/api/kb?q=E-3310').json()['total']>0
    assert client.get('/api/kb/missing').status_code==404
    assert client.get('/api/accounts').status_code==200


def test_quota_failure_never_becomes_completed_or_invents_metrics(client):
    from tam_agent.llm import GroqDailyQuotaError
    headers=login(client)
    def quota(ticket,ctx):
        raise GroqDailyQuotaError("Groq daily quota exhausted; no new result.")
    client.app.state.jobs.agent=quota
    response=client.post('/api/investigations',headers=headers,json={'ticket_id':'TKT-128253'})
    run=wait(client,response.json()['id'])
    assert run['status']=='failed'
    assert run['result'] is None and run['decision'] is None
    assert run['input_tokens'] is None and run['estimated_cost_usd'] is None
    assert 'daily quota exhausted' in run['error']
