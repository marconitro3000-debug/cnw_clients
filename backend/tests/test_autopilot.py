import asyncio
from fastapi.testclient import TestClient
from backend.autopilot import Autopilot, rule_quality, clean_query
from backend.continuous import ContinuousScanner
from backend.main import create_app
from backend.models import ContactInput
from backend.providers import Settings


class FakeModel:
    def __init__(self): self.calls = []
    async def health(self): return {'ready': True, 'installed': True}
    async def ask(self, name, system, data, schema, max_tokens=700, timeout=180):
        self.calls.append((name, data))
        if name == 'quality':
            return {'items': [{'id': i['id'], 'person': i['name'] != 'Información importante', 'firm': i['company'] != 'Top Funds Report 2026', 'reason': 'prueba'} for i in data['items']]}
        return {'queries': ['boutique equity fund manager Italia stock picking', 'site:linkedin.com/in cio equity fund', 'corta', 'boutique equity fund manager Italia stock picking']}


class Web:
    def __init__(self): self.queries = []
    async def search(self, query, rid):
        self.queries.append(query); return [], False


def person(db, name, company, linkedin=None, role='CIO', equity=True):
    return db.save_manual(ContactInput(name=name, company=company, role=role, equity=equity, country='España', employees_min=20, employees_max=20,
                                       linkedin_url=linkedin, note='Equipo verificado'))


def setup(tmp_path, api_key='tvly-auto-test'):
    settings = Settings(api_key=api_key, database_path=str(tmp_path / 't.sqlite'), shared_path=str(tmp_path / 'shared'))
    app = create_app(settings, provider=Web())
    model = FakeModel()
    pilot = Autopilot(app.state.crm, app.state.scanning, model, interval=0)
    app.state.autopilot = pilot
    return app, pilot, model


def test_rules_and_queries_are_conservative():
    assert rule_quality({'name': 'How Diligent Is Your Due Diligence?'})['status'] == 'junk'
    assert rule_quality({'name': 'The Big Bad Borrower Says No!'})['status'] == 'junk'
    assert rule_quality({'name': 'Freddie Lait'}) is None
    assert clean_query('site:linkedin.com/in cio equity') is None and clean_query('corta') is None
    assert clean_query('"boutique" equity fund manager Italia') == 'boutique equity fund manager Italia'


def test_cleaning_hides_junk_reversibly_and_flags_doubtful_firms(tmp_path):
    app, pilot, model = setup(tmp_path)
    db = app.state.db
    real = person(db, 'Freddie Lait', 'Latitude Investment Management', 'https://linkedin.com/in/freddie-auto')
    junk = person(db, 'Información importante', 'Latitude Investment Management')
    person(db, 'In This Story', 'Latitude Investment Management')
    doubtful = person(db, 'Ana Pérez', 'Top Funds Report 2026')
    asyncio.run(pilot.clean())
    assert [name for name, _ in model.calls] == ['quality']
    assert {i['name'] for i in model.calls[0][1]['items']} == {'Freddie Lait', 'Información importante', 'Ana Pérez'}  # rules handled the headline
    with TestClient(app) as client:
        names = [c['name'] for c in client.get('/api/crm/contacts?reachability=all').json()['items']]
        assert names == ['Ana Pérez', 'Freddie Lait']
        hidden = client.get('/api/crm/contacts?reachability=all&view=junk').json()['items']
        assert {c['name'] for c in hidden} == {'Información importante', 'In This Story'}
        assert db.contact(doubtful['id'])['quality']['status'] == 'doubtful_firm' and db.contact(real['id'])['quality']['by'] == 'Qwen'
        assert client.put(f"/api/crm/contacts/{junk['id']}/quality", json={'status': 'ok'}).json()['quality']['status'] == 'ok'
        assert client.get('/api/crm/contacts?reachability=all').json()['total'] == 3
        groups = client.get('/api/segments').json()['groups']
        assert 'In This Story' not in str(groups)
        assert any(f['doubtful_name'] for g in groups for f in g['firms'] if f['name'] == 'Top Funds Report 2026')
    asyncio.run(pilot.clean())
    assert len(model.calls) == 1  # reviewed contacts are not sent again


def test_web_batches_use_qwen_queue_then_templates_and_alternate_priority_firms(tmp_path):
    app, pilot, model = setup(tmp_path)
    app.state.scanning.streams['web']['config'] = {'autopilot': True}
    asyncio.run(pilot.plan())
    assert pilot.state['queue'] == ['boutique equity fund manager Italia stock picking']
    keywords, queries = pilot.web_batch()
    firms = [q['text'] for q in queries if q['phase'] == 'firms']
    assert firms[0] == 'boutique equity fund manager Italia stock picking' and len(firms) == 4 and pilot.state['queue'] == []
    assert any('{gestora}' in q['text'] for q in queries if q['phase'] == 'people')
    assert not any(q in pilot.state['used'][:-4] for q in firms)
    app.state.db.upsert_firm({'name': 'Latitude Investment Management', 'domain': 'latitudeim.com', 'equity': True})
    person(app.state.db, 'Freddie Lait', 'Latitude Investment Management', 'https://linkedin.com/in/freddie-batch')
    keywords, queries = pilot.web_batch()  # even cycles look for more people at firms that already fit
    assert 'prioritarias' in keywords and all('Latitude Investment Management' in q['text'] for q in queries)
    _, again = pilot.web_batch()
    assert all(q not in pilot.state['used'][:-4] for q in again if q['phase'] == 'firms')


def test_public_priority_and_restart_resume(tmp_path):
    app, pilot, model = setup(tmp_path)
    db = app.state.db
    review = person(db, 'Bea Gil', 'Otra Gestora', role='Responsable de comunicación')
    fit = person(db, 'Freddie Lait', 'Latitude Investment Management')
    fit_linked = person(db, 'Ana Ruiz', 'Latitude Investment Management', 'https://linkedin.com/in/ana-ruiz-auto')
    junk = person(db, 'Información importante', 'Latitude Investment Management')
    app.state.crm.set_meta(junk['id'], quality={'status': 'junk', 'reason': 'x', 'by': 'Qwen', 'at': '2026-01-01T00:00:00+00:00'})
    assert pilot.public_contacts() == [fit['id'], fit_linked['id'], review['id']]
    assert pilot.public_contacts() == []  # checked contacts wait a week

    async def run():
        await pilot.enable()
        streams = app.state.scanning.streams
        assert all(streams[s]['enabled'] and streams[s]['config']['autopilot'] for s in ('web', 'public', 'signals'))
        fresh = ContinuousScanner(app.state.runner, app.state.scanning.apollo, app.state.crm, interval=0)
        fresh.wake = lambda: None
        fresh.interrupt()
        restarted = Autopilot(app.state.crm, fresh, model, interval=0)
        restarted.wake = lambda: None
        await restarted.startup()
        assert fresh.streams['public']['enabled'] and fresh.streams['web']['config']['autopilot']
        assert 'continúa' in restarted.state['log'][0]['text']
        restarted.disable(); pilot.disable()
        assert not any(s['enabled'] for s in fresh.streams.values())
        await app.state.runner.shutdown()
    asyncio.run(run())


def test_without_search_key_only_public_data_and_cleaning_run(tmp_path):
    app, pilot, model = setup(tmp_path, api_key='')
    async def run():
        await pilot.enable()
        streams = app.state.scanning.streams
        assert streams['public']['enabled'] and not streams['web']['enabled'] and not streams['signals']['enabled']
        assert 'Tavily' in str(pilot.state['log'])
        pilot.disable(); await app.state.runner.shutdown()
    asyncio.run(run())


class Reader:
    """Answers like Qwen; some answers are invented on purpose and must be rejected."""
    def __init__(self): self.calls = []
    async def health(self): return {'ready': True, 'installed': True}
    async def ask(self, name, system, data, schema, max_tokens=700, timeout=180):
        self.calls.append(name)
        if name == 'firm':
            if data['firm'] == 'Keyridge Asset Management':
                return {'country': 'United Kingdom', 'country_quote': 'Specialist Asset Manager | UK & Ireland', 'equity': 'yes', 'equity_quote': 'From specialist equity strategies'}
            return {'country': 'France', 'country_quote': 'We invest for the long term', 'equity': 'yes', 'equity_quote': 'equities across Europe'}  # not in the sources
        if name == 'roles':
            return {'items': [{'id': i['id'], 'role': 'Portfolio Manager' if 'Sati' in i['name'] else 'CEO', 'quote': i['sources'][0] if 'Sati' in i['name'] else 'Rui Costa CEO'} for i in data['items']]}
        return None


def test_completion_only_accepts_facts_quoted_in_stored_sources(tmp_path):
    app, _, _ = setup(tmp_path)
    db, crm = app.state.db, app.state.crm
    pilot = Autopilot(crm, app.state.scanning, Reader(), interval=0)
    keyridge = db.upsert_firm({'name': 'Keyridge Asset Management', 'domain': 'keyridge.com', 'evidence': [
        {'field': 'company', 'value': 'Keyridge', 'url': 'https://keyridge.com/', 'quote': 'Specialist Asset Manager | UK & Ireland | Keyridge Asset Management. From specialist equity strategies to multi-asset ranges', 'observed_at': '2026-10-01T00:00:00+00:00'}]})
    other = db.upsert_firm({'name': 'Ficticia Gestión', 'domain': 'ficticia.example', 'evidence': [
        {'field': 'company', 'value': 'Ficticia', 'url': 'https://ficticia.example/', 'quote': 'We invest for the long term with a patient approach.', 'observed_at': '2026-10-01T00:00:00+00:00'}]})
    sati, _ = db.upsert_contact({'name': 'Cécile Sati', 'role': '', 'evidence': [{'field': 'name', 'value': 'Cécile Sati', 'url': 'https://keyridge.com/team', 'quote': 'Cécile Sati Portfolio Manager, Analyst Meet Cécile', 'observed_at': '2026-10-01T00:00:00+00:00'}]}, keyridge)
    costa, _ = db.upsert_contact({'name': 'Rui Costa', 'role': '', 'evidence': [{'field': 'name', 'value': 'Rui Costa', 'url': 'https://ficticia.example/team', 'quote': 'Rui Costa joined the team', 'observed_at': '2026-10-01T00:00:00+00:00'}]}, other)
    crm.identifiers()
    asyncio.run(pilot.complete())
    firm = db.firm(keyridge)
    assert firm['country'] == 'Reino Unido' and firm['equity'] is True
    assert any(e['field'] == 'country' and e['quote'] == 'Specialist Asset Manager | UK & Ireland' for e in firm['evidence'])
    assert db.firm(other).get('country') is None and db.firm(other).get('equity') is None  # invented quote rejected
    assert db.contact(sati)['role'] == 'Portfolio Manager' and db.contact(costa)['role'] == ''
    assert 'Keyridge Asset Management: país Reino Unido, renta variable' in pilot.state['log'][0]['text']
    calls = len(pilot.model.calls)
    asyncio.run(pilot.complete())
    assert len(pilot.model.calls) == calls  # already checked; retried after two weeks
