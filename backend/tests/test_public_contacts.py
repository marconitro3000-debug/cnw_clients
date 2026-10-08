import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.providers import Settings
from backend.models import ContactInput
from backend.crm_models import PublicSearchInput, InteractionInput
from backend.extract import extract_page, extract_person_page

FIRM={'name':'Aurora Asset Management','domain':'aurora.example'}
HTML='''<html><head><title>Aurora Asset Management</title></head><body><div class="team-card"><h2>Ana Pérez</h2><p>CIO</p><a href="mailto:ana@aurora.example">Email</a><a href="tel:+34 600 111 222">Phone</a><a href="https://linkedin.com/in/ana-public">LinkedIn</a><img data-src="https://media.licdn.com/ana.jpg" alt="Ana Pérez"></div><div class="team-card"><h2>Luis López</h2><p>Investment Director</p><a href="mailto:luis@aurora.example">Email</a><a href="tel:+34 600 999 888">Phone</a></div><footer><a href="mailto:info@aurora.example">Info</a><a href="tel:+34 911 222 333">Office</a></footer></body></html>'''


def test_public_channels_are_scoped_to_each_person_and_have_evidence():
    people=extract_page(HTML,'https://aurora.example/team',FIRM)['people']
    ana=next(p for p in people if p['name']=='Ana Pérez')
    assert ana['email']=='ana@aurora.example'
    assert [p['number'] for p in ana['phones']]==['+34 600 111 222']
    assert ana['photo_url']=='https://media.licdn.com/ana.jpg'
    assert ana['linkedin_url']=='https://www.linkedin.com/in/ana-public/'
    assert not any('info@' in str(e['value']) or 'luis@' in str(e['value']) for e in ana['evidence'])
    assert {'email','phone','photo_url','linkedin_url'}<={e['field'] for e in ana['evidence']}
    assert extract_person_page(HTML,'https://aurora.example/team',{'name':'Ana Pérez'}) is None


def test_structured_person_contacts_and_generic_email_not_assigned():
    raw={'@context':'https://schema.org','@type':'Person','name':'Ana Pérez','jobTitle':'CIO','worksFor':{'name':FIRM['name']},'email':'ana@aurora.example','telephone':'+34 600111222'}
    people=extract_page('<script type="application/ld+json">'+json.dumps(raw)+'</script>','https://aurora.example/team',FIRM)['people']
    assert people[0]['email']=='ana@aurora.example' and people[0]['phones'][0]['number']=='+34 600111222'
    raw['email']='info@aurora.example'
    assert not extract_page('<script type="application/ld+json">'+json.dumps(raw)+'</script>','https://aurora.example/team',FIRM)['people'][0].get('email')


class Pages:
    def __init__(self,gate=None):self.calls=[];self.gate=gate
    async def page(self,url):
        self.calls.append(url)
        if self.gate:await self.gate.wait()
        return {'html':HTML,'url':url,'observed_at':'2026-10-08T00:00:00Z'}


def build(tmp_path,gate=None):
    pages=Pages(gate)
    app=create_app(Settings(database_path=str(tmp_path/'test.sqlite'),shared_path=str(tmp_path/'shared')),fetcher_factory=lambda:pages)
    return app,pages


def person(app):
    c=app.state.db.save_manual(ContactInput(name='Ana Pérez',company=FIRM['name'],role='CIO'))
    app.state.db.upsert_firm(FIRM)
    return c


def test_public_scan_without_api_keys_updates_existing_and_preserves_manual_email(tmp_path):
    app,pages=build(tmp_path)
    with TestClient(app):
        c=person(app)
        app.state.crm.set_meta(c['id'],email='manual@aurora.example',email_status='manual')
        app.state.scanning.wake=lambda:None
        async def run():
            await app.state.scanning.start_public(PublicSearchInput(contact_ids=[c['id']],continuous=False))
            await asyncio.gather(*list(app.state.runner.tasks))
            result=app.state.db.latest_run();assert result['provider']=='public' and result['status']=='completed',result
            updated=app.state.db.contact(c['id'])
            assert updated['email']=='manual@aurora.example'
            assert updated['phones'][0]['number']=='+34 600 111 222'
            assert updated['photo_origin']=='LinkedIn'
            assert updated['reachable'] and updated['linkedin_url']
            assert len(app.state.db.contacts())==1
            assert result['credits']==0 and result['new_contacts']==0
            app.state.scanning.stop()
        asyncio.run(run())
        assert pages.calls
        assert app.state.crm.meta(c['id'])['email_candidates']==['ana@aurora.example']
        assert (tmp_path/'shared'/'contactos.csv').exists()


def test_public_scan_queues_behind_web_and_skips_contacted(tmp_path):
    app,pages=build(tmp_path)
    with TestClient(app):
        c=person(app)
        app.state.crm.interaction(c['id'],InteractionInput(author='Marco',channel='call',comment='Ya contactado'))
        web=app.state.db.create_run('web',[]);app.state.db.update_run(web,status='running');app.state.crm.set_run_metadata(web,provider='web')
        app.state.scanning.wake=lambda:None
        async def run():
            state=await app.state.scanning.start_public(PublicSearchInput(contact_ids=[c['id']],continuous=False))
            assert state['public']['status']=='queued'
            assert app.state.db.latest_run()['id']==web
            app.state.db.update_run(web,status='completed')
            await app.state.scanning.tick()
            assert not pages.calls
            assert not app.state.scanning.snapshot()['public']['enabled']
            assert app.state.crm.history(c['id'])[0]['comment']=='Ya contactado'
            app.state.scanning.stop()
        asyncio.run(run())


def test_public_cancellation_does_not_save_after_canceled_page(tmp_path):
    async def run():
        gate=asyncio.Event();app,pages=build(tmp_path,gate)
        c=person(app);rid=app.state.runner.start_public([c['id']])
        await asyncio.sleep(0)
        app.state.db.update_run(rid,cancel_requested=1)
        gate.set();await asyncio.gather(*list(app.state.runner.tasks))
        assert app.state.db.run(rid)['status']=='stopped'
        assert not app.state.db.contact(c['id'])['email']
    asyncio.run(run())


def test_score_and_contactability_filters_match_csv(tmp_path):
    app,_=build(tmp_path)
    with TestClient(app) as client:
        c=person(app)
        assert client.get('/api/crm/contacts?reachability=missing').json()['total']==1
        assert client.get('/api/crm/contacts?reachability=reachable').json()['total']==0
        app.state.crm.set_meta(c['id'],email='ana@aurora.example')
        assert client.get('/api/crm/contacts?reachability=reachable&min_score=40').json()['total']==1
        assert client.get('/api/crm/contacts?reachability=reachable&min_score=80').json()['total']==0
        assert 'Ana Pérez' not in client.get('/api/crm/contacts/export?reachability=missing').text
        assert 'ana@aurora.example' in client.get('/api/crm/contacts/export?reachability=reachable').text
        assert client.get('/api/crm/contacts?reachability=bad').status_code==422


def test_portrait_and_labelled_phone_are_extracted_from_a_person_card():
    html='<div class="team-card"><h2>Ana Pérez</h2><p>CIO</p><img src="/photos/ana.jpg"><img src="/icons/linkedin.svg"><p>Teléfono: +34 600 111 222</p></div>'
    ana=extract_page(html,'https://aurora.example/team',FIRM)['people'][0]
    assert ana['photo_url']=='https://aurora.example/photos/ana.jpg'
    assert ana['phones'][0]['number']=='+34 600 111 222'
    ambiguous=html.replace('<img src="/icons/linkedin.svg">','<img src="/photos/unknown.jpg">')
    assert extract_page(ambiguous,'https://aurora.example/team',FIRM)['people'][0]['photo_url'] is None


def test_web_discovery_persists_public_channels_without_apollo(tmp_path):
    class Search:
        async def search(self,text,rid):
            return [{'title':FIRM['name'],'url':'https://aurora.example','content':'Independent asset management, public equities, stock selection, Spain'}],False
    app,pages=build(tmp_path)
    with TestClient(app):
        app.state.runner.provider=Search()
        rid=app.state.db.create_run('equity',[{'text':'discover equity','phase':'firms'}])
        asyncio.run(app.state.runner.execute(rid))
        contacts=app.state.db.contacts()
        ana=next(c for c in contacts if c['name']=='Ana Pérez')
        assert ana['email']=='ana@aurora.example'
        assert ana['phones'][0]['number']=='+34 600 111 222'
        assert ana['photo_origin']=='LinkedIn'
        assert ana['contact_sources']
        assert app.state.db.run(rid)['status']=='completed'


def test_corporate_card_with_paragraph_name_and_link_to_personal_bio():
    from backend.extract import person_links
    html='<div class="h-team-card"><figure><img src="/javier.webp" alt="Javier Ruiz Aurora Asset Management"></figure><p class="h-team-card__name">Javier Ruiz</p><p>Director de Inversiones</p><a href="/gestores/javier">Ver ficha del gestor</a></div>'
    people=extract_page(html,'https://aurora.example/team',FIRM)['people']
    assert people[0]['name']=='Javier Ruiz'
    assert people[0]['photo_url']=='https://aurora.example/javier.webp'
    assert person_links(html,'https://aurora.example/team','Javier Ruiz')==['https://aurora.example/gestores/javier']
    assert person_links(html,'https://aurora.example/team','Ana Pérez')==[]


def test_www_redirect_checks_final_robots_and_preserves_html_accents(tmp_path,monkeypatch):
    import httpx
    from backend.providers import WebFetcher,ProviderError
    from backend.db import Database
    db=Database(tmp_path/'pages.sqlite');db.initialize()
    calls=[];block=[False]
    def handle(request):
        calls.append(str(request.url))
        if request.url.path=='/robots.txt':
            return httpx.Response(200,text='User-agent: *\nDisallow: /team' if block[0] and request.url.host=='www.aurora.example' else 'User-agent: *\nAllow: /')
        if request.url.host=='aurora.example':
            return httpx.Response(301,headers={'location':'https://www.aurora.example/team'})
        return httpx.Response(200,headers={'content-type':'text/html'},content='<meta charset="iso-8859-1"><h1>Ana Pérez</h1>'.encode('latin1'))
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))
    async def run():
        reader=WebFetcher(db)
        async def validate(url):pass
        reader.validate=validate
        page=await reader.page('https://aurora.example/team')
        assert 'Ana Pérez' in page['html'] and page['url']=='https://www.aurora.example/team'
        assert 'https://www.aurora.example/robots.txt' in calls
        block[0]=True
        other=WebFetcher(db);other.validate=validate
        with pytest.raises(ProviderError,match='robots'):
            await other.page('https://aurora.example/team?new=1')
    asyncio.run(run())
