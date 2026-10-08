from datetime import datetime, timedelta, timezone
from .domain import EUROPE, expand_queries
from .extract import valid_firm_name


def person_search_root(db,rid):
    crm=getattr(db,'crm',None)
    if not crm: return None
    seen=set()
    while rid and rid not in seen:
        seen.add(rid);meta=crm.run_metadata(rid)
        if meta.get('force_contact_id'): return rid
        rid=meta.get('parent_run_id')
    return None

def general_web_seed(db,rid):
    run=db.run(rid)
    if not run: raise LookupError('Búsqueda no encontrada.')
    root=person_search_root(db,rid)
    if not root: return run
    crm=db.crm
    with db.connect() as con:previous=con.execute('SELECT id FROM runs WHERE id<? ORDER BY id DESC',(root,)).fetchall()
    for row in previous:
        if crm.run_metadata(row[0]).get('provider','web')=='web' and not person_search_root(db,row[0]): return db.run(row[0])
    return {**run,'keywords':'renta variable','plan':expand_queries('renta variable')['queries']}

def prepare_next_batch(db, rid):
    run=general_web_seed(db,rid)
    rid=run['id']
    with db.connect() as con:
        used = {r[0] for r in con.execute("SELECT q.text FROM run_queries q JOIN runs r ON r.id=q.run_id WHERE q.status IN ('completed','failed') AND r.started_at>=?", ((datetime.now(timezone.utc)-timedelta(days=7)).isoformat(),))}
        firms = [db.firm(r[0]) for r in con.execute('SELECT id FROM firms ORDER BY updated_at,id')]
    templates = expand_queries(run['keywords'])['queries']
    queries = []
    seen = set(used)
    for firm in firms:
        if not valid_firm_name(firm['name']) or not firm['domain'] or firm.get('equity') is False:
            continue
        for item in templates:
            if item['phase'] != 'people':
                continue
            text = item['text'].replace('{gestora}', firm['name']).replace('{dominio}', firm['domain'])
            if text not in seen:
                queries.append({'text': text, 'phase': 'people'})
                seen.add(text)
        if len(queries) >= 12:
            break
    if not queries:
        for country in EUROPE:
            fresh = [q for q in expand_queries(run['keywords'], country)['queries'] if q['phase'] == 'firms' and q['text'] not in used]
            if fresh:
                queries = fresh + [q for q in templates if q['phase'] == 'people']
                break
    return {'keywords': run['keywords'], 'queries': queries[:20], 'parent_run_id': rid,
            'exhausted': not queries, 'max_queries': 20}
