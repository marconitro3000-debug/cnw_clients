"""Read existing public corporate pages. No Apollo, search API or invented addresses."""
import asyncio
from .domain import identity, now
from .extract import corporate_domain, domain_of, extract_page, extract_person_page, person_links, team_links
from .providers import ProviderError

async def execute_public(runner,rid):
    db=runner.db;crm=db.crm;ids=crm.run_metadata(rid).get('contact_ids',[])
    fetcher=runner.fetcher_factory();visited={};completed=0;updated=set();omitted=0;missing=0
    db.update_run(rid,status='running',total_queries=len(ids))
    try:
        for cid in ids:
            if runner.canceled(rid): break
            person=db.contact(cid)
            if not person: continue
            qid=db.add_query(rid,'Datos públicos · '+person['name'],'people');db.update_query(qid,'running')
            if person['blocked']:
                omitted+=1;db.update_query(qid,'completed');completed+=1;continue
            domain=person.get('domain','')
            if not domain or not corporate_domain('https://'+domain):
                missing+=1;db.update_query(qid,'completed');completed+=1;continue
            firm=db.firm(person['firm_id'])
            urls=list(dict.fromkeys(e['url'] for e in person.get('evidence',[]) if e.get('url') and corporate_domain(e['url']) and domain_of(e['url'])==domain))
            urls=urls[:3]+['https://'+domain]
            checked=set();index=0
            while index<len(urls) and len(checked)<6:
                if runner.canceled(rid):break
                url=urls[index];index+=1
                if url in checked: continue
                checked.add(url)
                if len(visited)>=16 and url not in visited: break
                try:
                    if url not in visited: visited[url]=await fetcher.page(url)
                    page=visited[url]
                    if runner.canceled(rid): break
                    extracted=extract_page(page['html'],page['url'],firm,page['observed_at'])
                    candidates=[p for p in extracted['people'] if identity(p['name'])==identity(person['name'])]
                    bio=extract_person_page(page['html'],page['url'],person,page['observed_at'])
                    if bio: candidates.append(bio)
                    for item in candidates:
                        if item.get('linkedin_url') and person.get('linkedin_url') and item['linkedin_url']!=person['linkedin_url']:
                            db.run_error(rid,'LinkedIn contradictorio para '+person['name']+'. Requiere revisión.');continue
                        contact_id,_=db.upsert_contact(item,person['firm_id'])
                        if contact_id!=cid: continue
                        crm.save_public_channels(cid,item);crm.observe(cid,rid,False,export=False)
                        if item.get('email') or item.get('phones') or item.get('photo_url') or item.get('linkedin_url'):updated.add(cid)
                    for link in person_links(page['html'],page['url'],person['name'])+team_links(page['html'],page['url']):
                        if link not in urls: urls.append(link)
                except (ProviderError,OSError) as error:
                    db.run_error(rid,domain+': '+str(error))
            completed+=1;db.update_query(qid,'completed')
            db.update_run(rid,completed_queries=completed,contacts_found=len(updated))
            crm.set_run_metadata(rid,omitted=omitted,unavailable=missing)
        db.update_run(rid,status='stopped' if runner.canceled(rid) else 'completed',finished_at=now(),completed_queries=completed,contacts_found=len(updated))
    except asyncio.CancelledError:
        db.update_run(rid,status='interrupted',finished_at=now());raise
    except Exception:
        db.run_error(rid,'Error al completar datos públicos. Se conservan los resultados.');db.update_run(rid,status='failed',finished_at=now())
    finally: await asyncio.to_thread(crm.export_shared)
