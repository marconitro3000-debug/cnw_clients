import asyncio
import json
from datetime import datetime, timedelta, timezone
import httpx
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.providers import Settings
from backend.crm_models import ApolloSearchInput, InteractionInput
from backend.models import ContactInput


def test_saved_contacts_sync_works_when_discovery_is_denied(tmp_path):
    settings=Settings(apollo_key='saved-fixture',database_path=str(tmp_path/'scout.sqlite'),shared_path=str(tmp_path/'shared'))
    app=create_app(settings)
    with TestClient(app) as client:
        provider=app.state.apollo.provider
        provider.record_access('denied','Discovery unavailable')
        calls=[]
        raw={'id':'saved-ana','name':'Ana Pérez','title':'CIO','email':'ana@example.org','linkedin_url':'https://linkedin.com/in/ana-saved','organization':{'name':'Aurora Asset Management','primary_domain':'aurora.example','country':'Spain','estimated_num_employees':30}}
        def handler(request):
            calls.append(request)
            assert request.url.path=='/api/v1/contacts/search'
            payload=json.loads(request.content)
            assert not any(k in payload for k in ('reveal_phone_number','reveal_personal_emails','person_titles','organization_locations'))
            return httpx.Response(200,json={'contacts':[raw]})
        provider.transport=httpx.MockTransport(handler)
        check=client.post('/api/apollo/connection-check?source=saved_contacts',json={})
        assert check.json()['saved_access']['status']=='verified'
        assert check.json()['access']['status']=='denied'
        assert check.json()['free_budget']==0
        async def run():
            body=ApolloSearchInput(source='saved_contacts',keywords='',continuous=True)
            await app.state.scanning.start_apollo(body)
            await asyncio.gather(*list(app.state.runner.tasks))
            result=app.state.db.latest_run()
            assert result['status']=='completed' and result['new_contacts']==1
            contacts=app.state.db.contacts();assert len(contacts)==1
            c=contacts[0];assert c['email']=='ana@example.org'
            assert c['apollo_contact_id']=='saved-ana'
            assert not c.get('apollo_id')
            await app.state.scanning.tick()
            await asyncio.gather(*list(app.state.runner.tasks))
            assert len(app.state.db.contacts())==1
            assert app.state.crm.dashboard()['totals']['identified']==1
            app.state.scanning.stop()
        app.state.scanning.wake=lambda:None
        app.state.scanning.interval=0
        asyncio.run(run())
        assert provider.access_status()['status']=='denied'
        with app.state.db.connect() as con:
            assert con.execute('SELECT COUNT(*) FROM apollo_reservations').fetchone()[0]==0
        assert len(calls)==3  # permission check and two pages; the repeated person remains unique


def test_saved_cache_and_empty_continuous_cycle_recheck_after_five_minutes(tmp_path):
    app=create_app(Settings(apollo_key='saved-fixture',database_path=str(tmp_path/'scout.sqlite'),shared_path=str(tmp_path/'shared')))
    with TestClient(app):
        calls=[]
        app.state.apollo.provider.transport=httpx.MockTransport(lambda r:(calls.append(r),httpx.Response(200,json={'contacts':[]}))[1])
        app.state.scanning.wake=lambda:None
        async def run():
            body=ApolloSearchInput(source='saved_contacts',keywords='',continuous=True)
            await app.state.scanning.start_apollo(body)
            await asyncio.gather(*list(app.state.runner.tasks))
            await app.state.scanning.tick()
            state=app.state.scanning.snapshot()['apollo']
            assert state['enabled'] and state['status']=='waiting'
            delay=datetime.fromisoformat(state['next_at'])-datetime.now(timezone.utc)
            assert 295<delay.total_seconds()<=300
            assert 'cinco minutos' in state['reason']
            await app.state.apollo.provider.search(body)
            assert len(calls)==1
            with app.state.db.connect() as con:
                con.execute('UPDATE cache SET created_at=?',((datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),))
            await app.state.apollo.provider.search(body)
            assert len(calls)==2
            app.state.scanning.stop()
        asyncio.run(run())


def test_saved_sync_preserves_contacted_person_and_comments(tmp_path):
    app=create_app(Settings(apollo_key='saved-fixture',database_path=str(tmp_path/'scout.sqlite'),shared_path=str(tmp_path/'shared')))
    with TestClient(app):
        c=app.state.db.save_manual(ContactInput(name='Ana Pérez',company='Aurora Asset Management',role='CIO',linkedin_url='https://linkedin.com/in/ana-saved'))
        app.state.crm.interaction(c['id'],InteractionInput(author='Marco',channel='call',comment='No volver a llamar'))
        raw={'id':'saved-ana','person_id':'person-ana','name':'Ana Pérez','title':'Other title','linkedin_url':'https://linkedin.com/in/ana-saved','organization_name':'Aurora Asset Management'}
        app.state.apollo.provider.transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'contacts':[raw]}))
        app.state.scanning.wake=lambda:None
        async def run():
            await app.state.scanning.start_apollo(ApolloSearchInput(source='saved_contacts',keywords='',continuous=True))
            await asyncio.gather(*list(app.state.runner.tasks))
            result=app.state.db.latest_run()
            assert result['omitted']==1 and result['candidates']==[]
            assert app.state.db.contact(c['id'])['role']=='CIO'
            assert app.state.crm.history(c['id'])[0]['comment']=='No volver a llamar'
            app.state.scanning.stop()
        asyncio.run(run())
