import asyncio
import csv
import io
import json
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.db import Database
from backend.domain import evidence, expand_queries, infer_signals, linkedin_url, now, role_points, safe_url, score_contact
from backend.extract import extract_page, result_person, team_links
from backend.main import create_app
from backend.models import ContactInput, SearchInput
from backend.providers import ProviderError, QuotaError, Settings, Tavily, WebFetcher
from backend.runner import Runner

@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite")
    database.initialize()
    return database

def firm(name="Aurora Asset Management", lo=11, hi=50, country="España", equity=True):
    return {"name": name, "domain": "aurora.example", "country": country,
            "employees_min": lo, "employees_max": hi, "equity": equity, "analysis": True,
            "issues": [], "evidence": [evidence("employees", [lo, hi], "https://aurora.example", "11–50 empleados"),
                evidence("equity", equity, "https://aurora.example", "Renta variable"),
                evidence("analysis", True, "https://aurora.example", "Stock selection")]}

def person(url="https://es.linkedin.com/in/ana-perez/?trk=test", role="Chief Investment Officer"):
    return {"name": "Ana Pérez", "role": role, "linkedin_url": url, "photo_url": None, "issues": [],
            "evidence": [evidence("role", role, "https://aurora.example/team", role)]}

def manual(**extra):
    return ContactInput(**{"name": "Ana Pérez", "company": "Aurora Asset Management", "role": "CIO",
        "country": "España", "employees_min": 30, "employees_max": 30, "equity": True,
        "analysis": True, "linkedin_url": "https://www.linkedin.com/in/ana-perez/", "note": "Fuente comprobada: ficha de equipo.", **extra})

def test_queries_have_preview_and_templates():
    expanded = expand_queries("value investing", "España")
    assert "value investing" in expanded["terms"]
    assert "head of equities" in expanded["terms"]
    assert all("España" in q["text"] for q in expanded["queries"] if q["phase"] == "firms")
    assert any("{gestora}" in q["text"] for q in expanded["queries"])
    assert expanded["max_queries"] == 20

@pytest.mark.parametrize("url", ["https://linkedin.com/company/acme", "https://linkedin.com.evil.test/in/ana/",
    "http://localhost/in/ana", "javascript:alert(1)", "https://linkedin.com/in/a%2Fb/", "https://user:pass@linkedin.com/in/ana"])
def test_invalid_profiles(url):
    assert linkedin_url(url) is None

def test_normalizes_real_profile_link():
    assert linkedin_url("https://es.linkedin.com/in/Ana-Perez?trk=x#about") == "https://www.linkedin.com/in/ana-perez/"

def test_score_requires_evidence_and_known_target():
    c = score_contact({**person(), **{k:v for k,v in firm().items() if k != "name"},
                       "name": "Ana Pérez", "evidence": person()["evidence"] + firm()["evidence"]})
    assert c["score"] == 100 and c["status"] == "qualified"
    c["evidence"] = []
    assert score_contact(c)["score"] == 0
    c["evidence"] = person()["evidence"] + firm()["evidence"]
    c["employees_min"] = c["employees_max"] = None
    unknown = score_contact(c)
    assert unknown["status"] == "qualified" and unknown["score"] == 80 and "Tamaño sin verificar" in unknown["missing"]
    assert score_contact({**c, "issues": ["possible_duplicate", "ai_review"]})["status"] == "qualified"
    assert score_contact({**c, "issues": ["conflict:country"]})["status"] == "review"
    c["employees_min"] = c["employees_max"] = 250
    assert score_contact(c)["status"] == "excluded"

@pytest.mark.parametrize("role,expected", [("CIO",40),("Directora de inversiones",40),("Head of Equities",40),("Portfolio Manager",25),("Investment Analyst",10),("Former CIO",0)])
def test_role_weights(role, expected):
    assert role_points(role) == expected

def test_private_equity_alone_is_not_listed_equity():
    assert infer_signals("Private equity asset manager")[0] is False
    assert infer_signals("Private equity and public equities")[0] is True

def test_role_uncertainty_does_not_score():
    c = {**person(), "issues": ["role_unverified"], "country": "España"}
    assert score_contact(c)["score"] == 0

HTML = """<html><head><title>Aurora Asset Management | Team</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
{"@type":"Organization","@id":"#company","name":"Aurora Asset Management","description":"Independent asset management, public equities and stock selection","address":{"@type":"PostalAddress","addressCountry":"ES"},"numberOfEmployees":{"@type":"QuantitativeValue","value":34}},
{"@type":"Person","name":"Ana Pérez","jobTitle":"Chief Investment Officer","worksFor":{"@id":"#company"},"sameAs":["https://es.linkedin.com/in/ana-perez/?trk=x"],"image":{"url":"/photos/ana.jpg"}},
{"@type":"Person","name":"José García","jobTitle":"CIO","worksFor":{"name":"Other Company"},"image":"/photos/other.jpg"}
]}</script></head><body><h1>Our investment team</h1><p>Independent asset management focused on public equities and stock selection.</p>
<a href="/team">Our team</a><a href="https://elsewhere.example/team">Other team</a>
<div class="team-member"><h3>Eva Martín</h3><p>Portfolio Manager</p><img src="/logo.png" alt="Aurora logo"><a href="https://linkedin.com/in/eva-martin">LinkedIn</a></div></body></html>"""

def test_structured_data_and_team_cards():
    extracted = extract_page(HTML, "https://aurora.example/team")
    assert extracted["firm"]["employees_min"] == 34
    assert extracted["firm"]["country"] == "España"
    assert extracted["firm"]["equity"] is True
    assert {p["name"] for p in extracted["people"]} == {"Ana Pérez", "Eva Martín"}
    ana = next(p for p in extracted["people"] if p["name"] == "Ana Pérez")
    eva = next(p for p in extracted["people"] if p["name"] == "Eva Martín")
    assert ana["photo_url"] == "https://aurora.example/photos/ana.jpg"
    assert eva["photo_url"] is None
    assert ana["linkedin_url"] == "https://www.linkedin.com/in/ana-perez/"
    assert team_links(HTML, "https://aurora.example") == ["https://aurora.example/team"]

def test_person_titles_require_name_and_company_evidence():
    result = {"url":"https://linkedin.com/in/ana-perez","title":"Ana Pérez - CIO - Aurora Asset Management | LinkedIn",
              "content":"CIO at Aurora Asset Management"}
    parsed = result_person(result, firm())
    assert parsed["name"] == "Ana Pérez"
    assert parsed["issues"] == []
    assert result_person({**result,"title":"Investment Team | LinkedIn"}, firm()) is None
    assert result_person({**result,"title":"Ana Pérez - CIO | LinkedIn","content":"Other Company"}, firm()) is None

def test_deduplication_and_conflicting_employers(db):
    f1 = db.upsert_firm(firm())
    a, created = db.upsert_contact(person(), f1)
    b, created_again = db.upsert_contact(person("https://www.linkedin.com/in/ANA-PEREZ"), f1)
    assert a == b and created and not created_again
    f2 = db.upsert_firm({**firm("Another Asset Management"), "domain":"another.example"})
    db.upsert_contact(person(), f2)
    contact = db.contact(a)
    assert contact["status"] == "review"
    assert contact["score"] == 0
    assert "conflict:company" in contact["issues"]
    assert len(db.contacts()) == 1

def test_fallback_identity_marks_cross_source_coincidence(db):
    f = db.upsert_firm(firm())
    p = person(None)
    a, _ = db.upsert_contact(p, f)
    p["evidence"] = [evidence("role", "CIO", "https://another.example/bio", "CIO")]
    b, _ = db.upsert_contact(p, f)
    assert a == b and "possible_duplicate" in db.contact(a)["issues"]

def test_overlapping_ranges_narrow_and_conflicts_remain_review(db):
    f = db.upsert_firm(firm(lo=11,hi=50))
    db.upsert_contact(person(), f)
    db.upsert_firm(firm(lo=30,hi=70))
    assert db.firm(f)["employees_min"] == 30
    assert db.firm(f)["employees_max"] == 50
    db.upsert_firm(firm(lo=500,hi=1000))
    assert db.firm(f)["employees_min"] is None
    assert db.contacts()[0]["status"] == "review"
    db.upsert_firm(firm())
    assert db.firm(f)["employees_min"] is None
    assert "conflict:employees" in db.firm(f)["issues"]

def test_manual_review_updates_all_contacts_at_company(db):
    a = db.save_manual(manual())
    b = db.save_manual(manual(name="Luis Pérez", linkedin_url="https://linkedin.com/in/luis-perez"))
    db.save_manual(manual(employees_min=500, employees_max=500), a["id"])
    assert db.contact(a["id"])["status"] == "excluded"
    assert db.contact(b["id"])["status"] == "excluded"

def test_restart_marks_active_runs_interrupted_without_losing_contacts(db):
    c = db.save_manual(manual())
    rid = db.create_run("equity", [])
    db.update_run(rid, status="running")
    db.interrupt_runs()
    assert db.run(rid)["status"] == "interrupted"
    assert db.contact(c["id"])["name"] == c["name"]

def test_cache_preserves_original_observation_and_expires(db):
    db.cache_put("q", [{"observed_at":"2026-01-01","content":"test"}])
    assert db.cache_get("q")[0]["observed_at"] == "2026-01-01"
    with db.connect() as con:
        con.execute("UPDATE cache SET created_at=?", ((datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),))
    assert db.cache_get("q") is None

def test_tavily_basic_only_and_cache_avoids_credits(db):
    settings = Settings(api_key="test-secret")
    rid = db.create_run("test", [])
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"results":[{"title":"Example","url":"https://example.com","content":"test"}]})
    provider = Tavily(settings, db, httpx.MockTransport(handler))
    first, cached = asyncio.run(provider.search("test", rid))
    second, cached_again = asyncio.run(provider.search("test", rid))
    assert not cached and cached_again and first == second
    assert len(calls) == 1
    assert calls[0]["search_depth"] == "basic" and calls[0]["auto_parameters"] is False
    assert db.credits_used(settings.account) == 1

@pytest.mark.parametrize("status", [402,432,433])
def test_provider_quota_errors_stop_instead_of_upgrading(db, status):
    settings = Settings(api_key="test")
    rid = db.create_run("test", [])
    provider = Tavily(settings, db, httpx.MockTransport(lambda request: httpx.Response(status)))
    with pytest.raises(QuotaError):
        asyncio.run(provider.search("test", rid))

def test_local_monthly_quota_is_enforced(db):
    settings = Settings(api_key="test",monthly_limit=1)
    rid = db.create_run("test", [])
    provider = Tavily(settings, db, httpx.MockTransport(lambda request:httpx.Response(200,json={"results":[]})))
    asyncio.run(provider.search("one",rid))
    with pytest.raises(QuotaError): asyncio.run(provider.search("two",rid))
    assert db.credits_used(settings.account) == 1

def test_page_reader_blocks_linkedin_and_private_addresses(db):
    reader = WebFetcher(db)
    for url in ["http://127.0.0.1","http://localhost","http://192.168.1.1","https://linkedin.com/in/ana","https://es.linkedin.com/company/aurora"]:
        with pytest.raises(ProviderError): asyncio.run(reader.validate(url))
    assert safe_url("https://linkedin.com:8443/in/ana") is False

class NoPages:
    async def page(self,url): raise ProviderError("Página sin HTML en la prueba.")

class FakeProvider:
    def __init__(self, quota_after=None, cancel_db=None):
        self.calls = []
        self.quota_after = quota_after
        self.cancel_db = cancel_db
    async def search(self,text,run_id):
        self.calls.append(text)
        await asyncio.sleep(0)
        if self.quota_after is not None and len(self.calls)>self.quota_after: raise QuotaError("Cuota agotada de prueba")
        if self.cancel_db and len(self.calls)==3: self.cancel_db.update_run(run_id,cancel_requested=1)
        if "discover" in text:
            return [{"title":"Aurora Asset Management | Equities","url":"https://aurora.example",
                "content":"Independent asset management in Spain. 11-50 employees. Public equities and stock selection."}], False
        return [{"title":"Ana Pérez - CIO - Aurora Asset Management | LinkedIn","url":"https://linkedin.com/in/ana-perez",
                 "content":"CIO at Aurora Asset Management"}], False

def run_fake(db, provider, people=3):
    plan = [{"text":"discover equity","phase":"firms"}]+[{"text":f'"{{gestora}}" profile {i}',"phase":"people"} for i in range(people)]
    rid = db.create_run("equity",plan)
    runner = Runner(db, Settings(), provider, NoPages)
    asyncio.run(runner.execute(rid))
    return db.run(rid)

def test_end_to_end_discovery_scoring_and_query_limit(db):
    provider = FakeProvider()
    run = run_fake(db,provider,people=25)
    assert run["status"] == "completed" and run["completed_queries"] == 20
    assert len(provider.calls)==20 and db.contacts()[0]["score"]==100
    assert db.contacts()[0]["status"] == "qualified"

def test_quota_retains_partial_results(db):
    run = run_fake(db,FakeProvider(quota_after=2),people=4)
    assert run["status"] == "quota_exhausted"
    assert len(db.contacts()) == 1 and run["contacts_found"] == 1

def test_cancellation_retains_partial_results(db):
    run = run_fake(db,FakeProvider(cancel_db=db),people=4)
    assert run["status"] == "stopped"
    assert len(db.contacts()) == 1
    assert run["completed_queries"] == 3

def test_empty_results_complete_without_inventing_people(db):
    class Empty:
        async def search(self, query, rid): return [],False
    run=run_fake(db,Empty())
    assert run["status"]=="completed" and run["contacts_found"]==0
    assert not db.contacts()

def test_literal_person_queries_are_attributed_to_discovered_firm(db):
    rid = db.create_run("equity",[{"text":"discover equity","phase":"firms"},{"text":"profile CIO Spain","phase":"people"}])
    asyncio.run(Runner(db,Settings(),FakeProvider(),NoPages).execute(rid))
    assert db.run(rid)["contacts_found"] == 1

@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database_path=str(tmp_path/"api.sqlite")))
    with TestClient(app) as c: yield c

def test_api_persistence_filters_review_and_csv(client):
    first=client.post("/api/contacts",json=manual().model_dump())
    assert first.status_code==201 and first.json()["score"]==100
    second=client.post("/api/contacts",json=manual(name="Luis Pérez",linkedin_url="https://linkedin.com/in/luis-perez",company="Otra Gestora",country="Francia",employees_min=70,employees_max=70).model_dump())
    assert second.status_code==201
    assert len(client.get("/api/contacts?country=España").json())==1
    assert len(client.get("/api/contacts?size_min=51&size_max=200").json())==1
    output=client.get("/api/contacts/export?country=España")
    rows=list(csv.reader(io.StringIO(output.content.decode("utf-8-sig")),delimiter=";"))
    assert len(rows)==2 and rows[1][0]=="Ana Pérez"
    assert rows[1][9]=="https://www.linkedin.com/in/ana-perez/"
    result=client.patch("/api/contacts/"+str(first.json()["id"]),json=manual(equity=None).model_dump())
    assert result.json()["status"]=="review"
    assert len(client.get("/api/contacts?status=review").json())==1
    assert client.get("/api/stats").json()["total"]==2

def test_api_rejects_invalid_urls_duplicate_and_range(client):
    bad=manual().model_dump()
    bad["linkedin_url"]="https://evil.test/in/ana"
    assert client.post("/api/contacts",json=bad).status_code==422
    bad=manual().model_dump();bad["employees_min"]=100;bad["employees_max"]=10
    assert client.post("/api/contacts",json=bad).status_code==422
    assert client.post("/api/contacts",json=manual().model_dump()).status_code==201
    assert client.post("/api/contacts",json=manual().model_dump()).status_code==409

def test_api_missing_key_invalid_status_and_untrusted_origin(client):
    assert not client.get("/api/health").json()["api_configured"]
    plan={"keywords":"equity","queries":[{"phase":"firms","text":"equity Spain"}]}
    assert client.post("/api/searches",json=plan).status_code==400
    assert client.get("/api/contacts?status=bad").status_code==422
    assert client.post("/api/contacts",json=manual().model_dump(),headers={"Origin":"https://evil.test"}).status_code==403

def test_csv_neutralizes_formulas(client):
    client.post("/api/contacts",json=manual(name="=Ana Pérez").model_dump())
    response=client.get("/api/contacts/export")
    assert "'=Ana Pérez" in response.text

def test_api_allows_only_one_active_search(tmp_path):
    app=create_app(Settings(api_key="test",database_path=str(tmp_path/"api.sqlite")))
    with TestClient(app) as client:
        rid=app.state.db.create_run("active",[])
        response=client.post("/api/searches",json={"keywords":"equity","queries":[{"text":"discover Spain","phase":"firms"}]})
        assert response.status_code==409
        assert client.post(f"/api/searches/{rid}/cancel").json()["status"]=="stopping"
        assert client.get("/api/searches/latest").json()["id"]==rid

def test_rejected_duplicate_does_not_modify_shared_company(client):
    client.post("/api/contacts",json=manual().model_dump())
    rejected=client.post("/api/contacts",json=manual(employees_min=500,employees_max=500).model_dump())
    assert rejected.status_code==409
    assert client.get("/api/contacts?status=all").json()[0]["employees_min"]==30

def test_accent_variants_do_not_erase_a_name(db):
    fid=db.upsert_firm(firm())
    db.upsert_contact(person(),fid)
    db.upsert_contact({**person(),"name":"Ana Perez"},fid)
    assert db.contacts()[0]["name"]=="Ana Pérez"
    assert "conflict:name" not in db.contacts()[0]["issues"]

def test_role_filter_matches_the_same_exact_role_as_the_interface(client):
    client.post("/api/contacts",json=manual(employees_min=None,employees_max=None).model_dump())
    client.post("/api/contacts",json=manual(name="Luis Pérez",role="Former CIO",linkedin_url="https://linkedin.com/in/luis-perez",employees_min=None,employees_max=None).model_dump())
    contacts=client.get("/api/contacts?status=all&role=CIO").json()
    assert [c["name"] for c in contacts]==["Ana Pérez"]
    csv_text=client.get("/api/contacts/export?status=all&role=CIO").text
    assert "Ana Pérez" in csv_text and "Luis Pérez" not in csv_text


def test_tavily_key_saved_locally_and_active_without_restart(tmp_path):
    from dotenv import dotenv_values
    env_path=tmp_path/".env"
    env_path.write_text("MONTHLY_SEARCH_LIMIT=37\nOTHER_SETTING=unchanged\n",encoding="utf-8")
    settings=Settings(database_path=str(tmp_path/"credentials.sqlite"),env_path=str(env_path))
    app=create_app(settings)
    key="tvly-test-secret-for-configuration"
    with TestClient(app) as client:
        assert not client.get("/api/health").json()["api_configured"]
        response=client.post("/api/settings/tavily",json={"api_key":"  "+key+"  "})
        assert response.status_code==200 and response.json()["api_configured"]
        assert key not in response.text
        assert client.get("/api/health").json()["api_configured"]
        assert key not in client.get("/api/health").text
        assert app.state.runner.provider.settings.api_key==key
        assert client.get("/api/health").json()["credits_used"]==0
    values=dotenv_values(env_path)
    assert values["TAVILY_API_KEY"]==key
    assert values["MONTHLY_SEARCH_LIMIT"]=="37" and values["OTHER_SETTING"]=="unchanged"

@pytest.mark.parametrize("key",["", "invalid-key", "tvly-key\ninjection", "tvly-"+"x"*600])
def test_invalid_tavily_key_does_not_change_settings(tmp_path,key):
    env_path=tmp_path/".env"
    settings=Settings(api_key="tvly-current-configured-key",database_path=str(tmp_path/"invalid-key.sqlite"),env_path=str(env_path))
    with TestClient(create_app(settings)) as client:
        response=client.post("/api/settings/tavily",json={"api_key":key})
        assert response.status_code==400
        assert not env_path.exists()
        assert settings.api_key=="tvly-current-configured-key"
        assert key not in response.text if key else True

def test_cannot_replace_key_during_active_search(tmp_path):
    env_path=tmp_path/".env"
    settings=Settings(api_key="tvly-original-key",database_path=str(tmp_path/"active-key.sqlite"),env_path=str(env_path))
    app=create_app(settings)
    with TestClient(app) as client:
        app.state.db.create_run("active",[])
        response=client.post("/api/settings/tavily",json={"api_key":"tvly-replacement-test-key"})
        assert response.status_code==409
        assert settings.api_key=="tvly-original-key" and not env_path.exists()

def test_key_configuration_rejects_untrusted_origin(tmp_path):
    settings=Settings(database_path=str(tmp_path/"origin-key.sqlite"),env_path=str(tmp_path/".env"))
    with TestClient(create_app(settings)) as client:
        response=client.post("/api/settings/tavily",json={"api_key":"tvly-test-configured-key"},headers={"Origin":"https://evil.test"})
        assert response.status_code==403 and not settings.api_key


@pytest.mark.parametrize("role,expected", [("CEO",40),("Co-Founder",40),("Managing Director",40),("Head of Equity Research",40),("Member of the Executive Board",40),
    ("Consejero Delegado",40),("Head of Business Development",0),("Sales Director",0),("Relationship Manager",0),("Director Comercial",0)])
def test_boutique_leaders_are_decision_makers_and_sales_roles_are_not(role, expected):
    assert role_points(role) == expected

def test_compatible_source_disagreements_do_not_block_a_contact():
    base = {**person(), **{k:v for k,v in firm().items() if k != "name"}, "name": "Ana Pérez", "evidence": person()["evidence"] + firm()["evidence"]}
    offices = [evidence("country", c, "https://aurora.example/" + c, c) for c in ("España", "Luxemburgo", "España")]
    c = score_contact({**base, "country": "", "issues": ["conflict:country"], "evidence": base["evidence"] + offices})
    assert c["country"] == "España" and c["status"] == "qualified"
    abroad = score_contact({**base, "country": "", "issues": ["conflict:country"], "evidence": base["evidence"] + [evidence("country", "Estados Unidos", "https://x.example", "US")]})
    assert abroad["status"] == "review"
    roles = [evidence("role", r, "https://aurora.example/team", r) for r in ("Gestor", "Gestor de Fondos de Renta Variable")]
    no_role = [e for e in base["evidence"] if e["field"] != "role"]
    resolved = score_contact({**base, "role": "", "issues": ["conflict:role"], "evidence": no_role + roles + [evidence("role", "Gestor", "https://aurora.example/b", "Gestor")]})
    assert resolved["role"] == "Gestor de Fondos de Renta Variable" and resolved["reasons"][0]["points"] == 25
    mixed = score_contact({**base, "role": "", "issues": ["conflict:role"], "evidence": no_role + roles + [evidence("role", "Sales Director", "https://x.example", "Sales Director")]})
    assert mixed["status"] == "review"
