import asyncio
from backend.autopilot import Autopilot
from backend.crm_models import InteractionInput
from backend.db import Database
from backend.crm import CRM
from backend.dedup import merge_obvious, candidate_pairs, person_tokens, own_domain, firm_key
from backend.main import create_app
from backend.providers import Settings


def person(name, url, role='CIO', linkedin=None):
    return {'name': name, 'role': role, 'linkedin_url': linkedin, 'evidence': [{'field': 'name', 'value': name, 'url': url, 'quote': name + ' ' + role, 'observed_at': '2026-10-01T00:00:00+00:00'}]}


def setup(tmp_path):
    app = create_app(Settings(api_key='', database_path=str(tmp_path / 't.sqlite'), shared_path=str(tmp_path / 'shared')))
    return app, app.state.db, app.state.crm


def test_name_helpers():
    assert person_tokens('COURT, Rachel Diane') == ['rachel', 'diane', 'court']
    assert person_tokens('Stella Ma, CFA®') == ['stella', 'ma']
    assert own_domain('Trinity Street Asset Management', 'trinitystreetam.com') and not own_domain('Trinity Street Asset Management', 'imgp.com')
    assert firm_key('Impax Asset Management Ltd') == firm_key('Impax Asset Management')


def test_directory_copies_of_a_firm_merge_and_are_not_recreated(tmp_path):
    app, db, crm = setup(tmp_path)
    own = db.upsert_firm({'name': 'Impax Asset Management', 'domain': 'impaxam.com', 'equity': True})
    with db.connect() as con:  # a copy saved before this fix
        con.execute("INSERT INTO firms(name,name_key,domain,data,updated_at) VALUES('Impax Asset Management','impax asset management','tracxn.com','{\"name\":\"Impax Asset Management\",\"domain\":\"tracxn.com\",\"country\":\"Reino Unido\",\"evidence\":[],\"issues\":[]}','2026-01-01')")
        copy = con.execute("SELECT id FROM firms WHERE domain='tracxn.com'").fetchone()[0]
    crm.identifiers()
    cid, _ = db.upsert_contact(person('Ross Pamphilon', 'https://tracxn.com/impax'), copy)
    crm.interaction(cid, InteractionInput(author='Marco', channel='call', comment='Llamada'))
    # Two different firms sharing a generic name stay separate.
    db.upsert_firm({'name': 'Gestora de Fondos de Inversión', 'domain': 'horosam.com'})
    db.upsert_firm({'name': 'Gestora de Fondos de Inversión', 'domain': 'bestinver.es'})
    firms, people = merge_obvious(crm)
    assert [(f[0], f[1]) for f in firms] == [('Impax Asset Management', 'tracxn.com')]
    moved = db.contact(cid)
    assert moved['firm_id'] == own and moved['domain'] == 'impaxam.com' and moved['country'] == 'Reino Unido'
    assert crm.history(cid)[0]['comment'] == 'Llamada'
    with db.connect() as con:
        assert con.execute("SELECT count(*) FROM firms WHERE name_key LIKE 'gestora de fondos%'").fetchone()[0] == 2
    # New third-party copies reuse the firm, and the firm's own site replaces a directory domain.
    assert db.upsert_firm({'name': 'Impax Asset Management', 'domain': 'pitchbook.com'}) == own
    assert db.firm(own)['domain'] == 'impaxam.com'
    other = Database(tmp_path / 'other.sqlite'); other.initialize(); clone = CRM(other, tmp_path / 'shared'); clone.import_shared()
    assert len(other.contacts()) == 1 and not clone.conflicts()


def test_people_merge_keeps_linkedin_history_and_channels(tmp_path):
    app, db, crm = setup(tmp_path)
    fid = db.upsert_firm({'name': 'Latitude Investment Management', 'domain': 'latitudeim.com', 'equity': True})
    plain, _ = db.upsert_contact(person('FREDDIE LAIT', 'https://latitudeim.com/team'), fid)
    with db.connect() as con:  # identical names saved separately by an older version
        con.execute("UPDATE contacts SET name_key='old' WHERE id=?", (plain,))
    linked, _ = db.upsert_contact(person('Freddie Lait', 'https://news.example/a', linkedin='https://linkedin.com/in/freddie-dedup'), fid)
    crm.identifiers()
    crm.set_meta(plain, email='freddie@latitudeim.com', phones=[{'number': '+44 20 1234 5678'}])
    crm.interaction(plain, InteractionInput(author='Marco', channel='email', comment='Primer correo'))
    other_person, _ = db.upsert_contact(person('Freddie Ryecart', 'https://latitudeim.com/team', 'Partner', 'https://linkedin.com/in/ryecart-dedup'), fid)
    firms, people = merge_obvious(crm)
    assert people == ['FREDDIE LAIT'] and db.contact(plain) is None
    kept = db.contact(linked)
    assert kept['linkedin_url'] == 'https://www.linkedin.com/in/freddie-dedup/' and kept['email'] == 'freddie@latitudeim.com'
    assert kept['phones'][0]['number'] == '+44 20 1234 5678' and crm.history(linked)[0]['comment'] == 'Primer correo'
    assert db.contact(other_person)  # same firm, different person
    assert len(list((tmp_path / 'shared' / 'contacts').glob('*.json'))) == 2


class Judge:
    def __init__(self): self.calls = []
    async def health(self): return {'ready': True, 'installed': True}
    async def ask(self, name, system, data, schema, max_tokens=700, timeout=180):
        self.calls.append(name)
        if name != 'dedup': return None
        return {'results': [{'id': p['id'], 'same': p['a']['name'].endswith('Bell') and p['b']['name'].endswith('Bell'), 'reason': 'prueba'} for p in data['pairs']]}


def test_ambiguous_pairs_go_to_qwen_once(tmp_path):
    app, db, crm = setup(tmp_path)
    fid = db.upsert_firm({'name': 'Trinity Street Asset Management', 'domain': 'trinitystreetam.com', 'equity': True})
    ed, _ = db.upsert_contact(person('Ed Bell', 'https://trinitystreetam.com/team', 'Partner'), fid)
    edward, _ = db.upsert_contact(person('Edward Bell', 'https://trinitystreetam.com/about', 'Partner', 'https://linkedin.com/in/edward-bell-dedup'), fid)
    tim, _ = db.upsert_contact(person('Tim Race', 'https://trinitystreetam.com/team', 'Partner'), fid)
    tom, _ = db.upsert_contact(person('Tom Race', 'https://trinitystreetam.com/team', 'Analyst'), fid)
    crm.identifiers()
    assert {tuple(sorted((a['name'], b['name']))) for a, b in candidate_pairs(db.contacts())[1]} == {('Ed Bell', 'Edward Bell')}
    judge = Judge(); pilot = Autopilot(crm, app.state.scanning, judge, interval=0)
    asyncio.run(pilot.dedup())
    assert db.contact(ed) is None and db.contact(edward)['linkedin_url'] and db.contact(tim) and db.contact(tom)
    assert 'Qwen fusionó' in pilot.state['log'][0]['text']
    asyncio.run(pilot.dedup())
    assert judge.calls == ['dedup']
