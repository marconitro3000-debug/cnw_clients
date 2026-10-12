"""Dated commercial research signals. Evidence of an event is not buying intent."""
import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from bs4 import BeautifulSoup
from .domain import normalized, now, safe_url, is_linkedin
from .extract import domain_of, corporate_domain, jsonld_nodes, valid_firm_name
from .providers import ProviderError, QuotaError

KINDS = {
    'fund_launch': ('Nuevo fondo o estrategia', r'\b(?:launch(?:es|ed|ing)?|lanz(?:a|amos|ado|amiento|ara)|new fund|nuevo fondo|nueva estrategia)\b', 25),
    'hiring': ('Contratación del equipo', r'\b(?:hir(?:e|es|ed|ing)|recruit(?:ing|ment)?|vacan(?:cy|cies|te|tes)|contrat(?:a|amos|acion)|buscamos|incorpora(?:cion|mos)?|se incorpora)\b', 20),
    'expansion': ('Expansión', r'\b(?:expan(?:d|ds|ded|ding|sion)|new office|nueva oficina|abre una oficina|entr(?:a|ada) en|nuevo mercado)\b', 20),
    'leadership': ('Cambio de responsable', r'\b(?:appoint(?:s|ed|ment)?|nombr(?:a|ado|amiento)|nuevo cio|new cio|nueva directora?|nuevo director)\b', 15),
    'technology': ('Herramientas y datos', r'\b(?:adopt(?:s|ed|ing)?|implement(?:s|ed|ing|a|ado|acion)?|automatiza(?:cion|mos)?|technology partner|alianza tecnologica|data platform)\b', 20),
    'event_driven': ('Estrategia event-driven', r'\bevent[ -]driven\b', 0),
}
SIGNAL_SCHEMA={'type':'object','properties':{'signals':{'type':'array','items':{'type':'object','properties':{'kind':{'type':'string','enum':list(KINDS)},'quote':{'type':'string'}},'required':['kind','quote'],'additionalProperties':False}}},'required':['signals'],'additionalProperties':False}

def date_value(value):
    if not isinstance(value,str) or not value.strip(): return None
    try:
        stamp=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
    except ValueError:
        try: stamp=parsedate_to_datetime(value)
        except (ValueError,TypeError,OverflowError): return None
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).date().isoformat()

def canonical_source(value):
    if not safe_url(value): return None
    p=urlparse(value)
    params=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith(('utm_','trk','ref'))]
    return urlunparse((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/') or '/',p.params,urlencode(params),''))

def source_document(result,page=None):
    """Keep publication dates separate from the provider's estimated update date."""
    title=result.get('title','');text=result.get('content','');dates=[]
    if page:
        soup=BeautifulSoup(page['html'],'html.parser')
        for node in jsonld_nodes(soup):
            if node.get('datePublished'): dates.append(date_value(node['datePublished']))
        for m in soup.select('meta[property="article:published_time"],meta[name="date"],meta[itemprop="datePublished"]'):
            dates.append(date_value(m.get('content')))
        for t in soup.select('time[datetime]'): dates.append(date_value(t['datetime']))
        for tag in soup(['script','style','nav','footer','aside']):tag.decompose()
        scope=soup.find('article') or soup.find('main') or soup.body or soup
        # Preserve paragraph boundaries without breaking inline names and titles.
        # A flattened newsroom can exceed the sentence limit and lose every signal.
        for block in scope.find_all(['p','div','li','h1','h2','h3','h4','blockquote','br']):
            block.insert_after('\n')
        text='\n'.join(' '.join(line.split()) for line in scope.get_text(' ').splitlines() if line.strip())[:16000]
        heading=scope.find('h1')
        if heading:title=heading.get_text(' ',strip=True)[:300]
    unique=set(d for d in dates if d)
    if len(unique)==1:published=unique.pop();basis='document'
    elif len(unique)>1:published=None;basis='conflicting'
    else:published=date_value(result.get('published_date'));basis='provider_estimate' if published else 'unknown'
    return {'url':(page or result).get('url',''),'title':title[:300],'text':text,'published_at':published,'date_basis':basis,'observed_at':(page or result).get('observed_at') or now()}

def associated(quote,firm,url):
    text=normalized(quote)
    name=normalized(firm['name'])
    # Third-party sources must explicitly attribute the event to the researched firm.
    if len(name)>=4 and name in text:return True
    domain=firm.get('domain','')
    if domain and domain.lower() in quote.lower():return True
    primary=domain_of(url)==domain
    return bool(primary and re.search(r'\b(?:we|our|nosotros|nuestra|nuestro|lanzamos|buscamos|contratamos|incorporamos|expandimos|automatizamos)\b',text))

MONTHS={
    'january':1,'enero':1,'february':2,'febrero':2,'march':3,'marzo':3,'april':4,'abril':4,
    'may':5,'mayo':5,'june':6,'junio':6,'july':7,'julio':7,'august':8,'agosto':8,
    'september':9,'septiembre':9,'setiembre':9,'october':10,'octubre':10,
    'november':11,'noviembre':11,'december':12,'diciembre':12}

def explicit_event_dates(text):
    dates=[date_value(v) for v in re.findall(r'\b\d{4}-\d{2}-\d{2}\b',text)]
    clean=normalized(text)
    months='|'.join(MONTHS)
    for day,month,year in re.findall(r'\b(\d{1,2})(?:st|nd|rd|th)?(?: de)? ('+months+r')(?: de)? (\d{4})\b',clean):
        dates.append(date_value(f'{year}-{MONTHS[month]:02d}-{int(day):02d}'))
    for month,day,year in re.findall(r'\b('+months+r') (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})\b',clean):
        dates.append(date_value(f'{year}-{MONTHS[month]:02d}-{int(day):02d}'))
    # Numeric US and European dates are ambiguous without an explicit locale.
    return sorted(set(v for v in dates if v))

def evidence_record(kind,quote,document,firm,method='rules'):
    if kind not in KINDS or not isinstance(quote,str) or not 12<=len(quote)<=900:return None
    if normalized(quote) not in normalized(document['text']):return None
    if not associated(quote,firm,document['url']):return None
    text=normalized(quote)
    match=re.search(KINDS[kind][1],text)
    if not match:return None
    # A fund's analysis of an issuer's growth is not growth of the fund itself.
    if kind!='event_driven':
        if re.search(r'\b(?:according to|segun|analys(?:es|is|ing)|analiza(?:mos)?|portfolio company|participada|invertimos en|invests? in|our investment in)\b',text):return None
        name=normalized(firm['name']);subject=text[:match.start()]
        attributed=name in subject or bool(firm.get('domain') and firm['domain'].lower() in subject)
        first_person=domain_of(document['url'])==firm.get('domain') and bool(re.search(r'\b(?:we|our|nosotros|nuestra|nuestro)\b',subject) or re.search(r'\b(?:lanzamos|buscamos|contratamos|incorporamos|expandimos|automatizamos)\b',text))
        if not attributed and not first_person:return None
    # Reporting a denial or an old event must not become a new expansion opportunity.
    if re.search(r'\b(?:not|never|no|nunca|sin)\s+(?:\w+\s+){0,2}(?:launch|lanz|hir|contrat|expand|implement|adopt|event[ -]driven|appoint|nombr)',text):return None
    if kind=='fund_launch' and not re.search(r'\b(?:funds?|fondos?|strateg(?:y|ies)|estrategias?)\b',text):return None
    if kind=='technology' and not re.search(r'\b(?:data|datos|python|tecnolog|technology|platform|plataforma|research|analisis|analytics|ai|ia)\w*\b',text):return None
    event_dates=explicit_event_dates(quote)
    years=[int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b',quote)]
    publication=document['published_at']
    historical=bool(years and publication and datetime(max(years),12,31,tzinfo=timezone.utc).date()<datetime.now(timezone.utc).date()-timedelta(days=90))
    event_date=event_dates[0] if len(set(event_dates))==1 else None
    return {'kind':kind,'quote':quote,'source_url':canonical_source(document['url']),'title':document['title'],
        'published_at':publication,'event_at':event_date,'event_date_ambiguous':len(event_dates)>1,'historical':historical,'future_event':bool(years and min(years)>datetime.now(timezone.utc).year),'date_basis':document['date_basis'],
        'observed_at':document['observed_at'],'method':method,'review':'pending' if method=='local_model' else 'detected','reviews':[]}

def extract_signals(document,firm,proposals=None):
    if not canonical_source(document['url']):return []
    records=[]
    # Sentences preserve local company attribution instead of treating a whole news page as evidence.
    for sentence in re.split(r'(?<=[.!?])\s+|\n+',document['text']):
        sentence=sentence.strip()
        if not 12<=len(sentence)<=900:continue
        for kind in KINDS:
            item=evidence_record(kind,sentence,document,firm)
            if item:records.append(item)
    for proposed in proposals or []:
        if not isinstance(proposed,dict):continue
        item=evidence_record(proposed.get('kind'),proposed.get('quote'),document,firm,'local_model')
        if item:records.append(item)
    result=[];seen=set()
    for r in records:
        token=(r['kind'],normalized(r['quote']))
        if token not in seen:seen.add(token);result.append(r)
    return result[:12]

def recency(signal,days=90):
    today=datetime.now(timezone.utc).date()
    date=signal.get('event_at') or signal.get('published_at')
    if signal.get('historical'):return 'historical'
    if signal.get('future_event'):return 'future'
    if signal.get('event_date_ambiguous'):return 'undated'
    if not date:return 'undated'
    stamp=datetime.fromisoformat(date).date()
    if stamp>today:return 'future'
    if stamp<today-timedelta(days=days):return 'old'
    return 'recent' if signal.get('date_basis')=='document' or signal.get('review')=='confirmed' else 'estimated'

def save_signal(crm,firm_id,signal):
    firm=crm.db.firm(firm_id)
    if not firm.get('uuid'):
        crm.identifiers()
        firm=crm.db.firm(firm_id)
    key=str(uuid.uuid5(uuid.NAMESPACE_URL,firm['uuid']+'|'+signal['source_url']+'|'+signal['kind']+'|'+normalized(signal['quote'])))
    with crm.db.connect() as con:
        old=con.execute('SELECT data FROM business_signals WHERE uuid=?',(key,)).fetchone()
        record={**signal,'uuid':key,'firm_uuid':firm['uuid']}
        if old:
            old=json.loads(old[0]);record.update(review=old.get('review',record['review']),reviews=old.get('reviews',[]))
            # Preserve the evidence reviewed by a human.
            if old.get('reviews'):record={**old,'observed_at':signal['observed_at']}
        con.execute('INSERT OR REPLACE INTO business_signals VALUES(?,?,?)',(key,firm['uuid'],json.dumps(record,ensure_ascii=False)))
    return key,not bool(old)

def list_signals(crm,days=90,firm_id=None,kind='',recent_only=False):
    with crm.db.connect() as con:
        firms={r['uuid']:dict(r) for r in con.execute('SELECT id,uuid,name,domain FROM firms')}
        records=[json.loads(r[0]) for r in con.execute('SELECT data FROM business_signals')]
    result=[]
    for s in records:
        f=firms.get(s['firm_uuid'])
        if not f or firm_id and f['id']!=firm_id or kind and s['kind']!=kind:continue
        state=recency(s,days)
        if recent_only and (state not in ('recent','estimated') or s['review']=='rejected'):continue
        result.append({**s,'company':f['name'],'firm_id':f['id'],'domain':f['domain'],'label':KINDS[s['kind']][0],'recency':state})
    return sorted(result,key=lambda r:r.get('published_at') or '',reverse=True)

def review_signal(crm,key,decision):
    if decision not in ('confirmed','rejected','pending'):raise ValueError('Revisión no válida.')
    with crm.db.connect() as con:
        row=con.execute('SELECT data FROM business_signals WHERE uuid=?',(key,)).fetchone()
        if not row:raise LookupError('Señal no encontrada.')
        r=json.loads(row[0]);r['review']=decision
        r.setdefault('reviews',[]).append({'decision':decision,'author':crm.setting('actor','Marco'),'at':now()})
        con.execute('UPDATE business_signals SET data=? WHERE uuid=?',(json.dumps(r,ensure_ascii=False),key))
    crm.export_shared()
    return r

# Global groups and banks are not the boutiques being prospected; their newsrooms drown out target news.
LARGE_GROUP=r'\b(?:j\.? ?p\.? ?morgan|jpmorgan|goldman sachs|morgan stanley|blackrock|vanguard|fidelity|capital group|amundi|bnp paribas|axa|allianz|dws|ubs|credit suisse|pictet|vontobel|schroders?|abrdn|aberdeen|invesco|franklin templeton|state street|santander|bbva|caixabank|natixis|columbia threadneedle|m&g|legal & general|nordea|storebrand|rbc|bluebay|hsbc|deutsche|union investment|generali|eurizon|robeco|nn investment|aegon|pimco|t\. ?rowe|wellington|nuveen|janus henderson|lazard|candriam|credit mutuel|la francaise|ostrum|mirabaud|lombard odier|julius baer|kutxabank|ibercaja|mutuactivos|unicaja|sabadell|bankinter|mapfre|dnb|principal asset|banco|bank)\b'

def large_group(firm):
    return bool(re.search(LARGE_GROUP,normalized(firm.get('name','')))) or (firm.get('employees_min') or 0)>200

def eligible_firms(crm,ids=None):
    """Firms being prospected: a real boutique with at least one agenda contact that fits or is pending review."""
    contacts=crm.db.contacts();blocked={};active=set()
    for c in contacts:
        blocked.setdefault(c['firm_id'],[]).append(c['blocked'])
        if c['status']!='excluded' and (c.get('quality') or {}).get('status')!='junk':active.add(c['firm_id'])
    with crm.db.connect() as con:firms=[crm.db.firm(r[0]) for r in con.execute('SELECT id FROM firms ORDER BY id')]
    return [f for f in firms if (not ids or f['id'] in ids) and f['id'] in active and not large_group(f) and valid_firm_name(f['name']) and corporate_domain('https://'+f['domain']) and f.get('equity') is not False and not (blocked.get(f['id']) and all(blocked[f['id']]))]

def signal_queries(firm):
    name=firm['name'].replace('"','');domain=firm['domain']
    return [f'"{name}" new fund launch expansion nuevo fondo',
            f'site:{domain} "{name}" news careers hiring technology',
            f'"{name}" event-driven quantamental new strategy']

async def execute_signal_scan(runner,rid):
    db=runner.db;crm=db.crm;meta=crm.run_metadata(rid);days=meta.get('days',90)
    firms=eligible_firms(crm,meta.get('firm_ids',[]))[:4];fetcher=runner.fetcher_factory()
    found=set();fresh=0;completed=0;pages={};model_calls=0
    db.update_run(rid,status='running',total_queries=len(firms)*3)
    try:
        for firm in firms:
            for query in signal_queries(firm):
                if runner.canceled(rid):break
                qid=db.add_query(rid,query,'signals');db.update_query(qid,'running')
                try:
                    if hasattr(runner.provider,'search_signals'):results,cached=await runner.provider.search_signals(query,rid,days)
                    else:results,cached=await runner.provider.search(query,rid)
                except ProviderError as e:
                    db.update_query(qid,'failed',error=str(e));raise
                completed+=1;db.update_query(qid,'completed',cached)
                db.update_run(rid,completed_queries=completed)
                for result in results[:5]:
                    if runner.canceled(rid):break
                    url=result.get('url','');page=None
                    if not safe_url(url):continue
                    if domain_of(url)!=firm['domain'] and not associated(str(result.get('title') or '')+' '+str(result.get('content') or ''),firm,url):continue
                    # LinkedIn posts may be returned as public snippets; never automate a session.
                    if not is_linkedin(url) and (url in pages or len(pages)<16):
                        try:
                            if url not in pages:
                                pages[url]=None
                                pages[url]=await fetcher.page(url)
                            page=pages[url]
                        except (ProviderError,OSError) as e:db.run_error(rid,str(e))
                    if runner.canceled(rid):break
                    doc=source_document(result,page);records=extract_signals(doc,firm)
                    model=getattr(runner,'local_model',None)
                    if not records and page and model and model_calls<4 and associated(doc['text'],firm,doc['url']):
                        model_calls+=1
                        task=asyncio.create_task(model.extract_signals(page,firm))
                        try:
                            while not task.done():
                                if runner.canceled(rid):task.cancel();break
                                await asyncio.wait({task},timeout=.25)
                            proposals=[] if runner.canceled(rid) or task.cancelled() else await task
                            if not runner.canceled(rid):records=extract_signals(doc,firm,proposals)
                        except ProviderError as e:db.run_error(rid,str(e))
                        finally:
                            if not task.done():task.cancel()
                            await asyncio.gather(task,return_exceptions=True)
                    if runner.canceled(rid):break
                    for record in records:
                        key,created=save_signal(crm,firm['id'],record);found.add(key);fresh+=int(created)
                crm.set_run_metadata(rid,signals_found=len(found),new_signals=fresh)
                await asyncio.to_thread(crm.export_shared)
            if runner.canceled(rid):break
        db.update_run(rid,status='stopped' if runner.canceled(rid) else 'completed',finished_at=now())
    except QuotaError as e:db.run_error(rid,str(e));db.update_run(rid,status='quota_exhausted',finished_at=now())
    except ProviderError as e:db.run_error(rid,str(e));db.update_run(rid,status='failed',finished_at=now())
    except asyncio.CancelledError:db.update_run(rid,status='interrupted',finished_at=now());raise
    except Exception:
        db.run_error(rid,'Error al analizar señales; los resultados guardados se conservan.')
        db.update_run(rid,status='failed',finished_at=now())
    finally:await asyncio.to_thread(crm.export_shared)

def validate_shared_signal(record):
    uuid.UUID(record['uuid']);uuid.UUID(record['firm_uuid'])
    if record.get('kind') not in KINDS or record.get('review') not in ('confirmed','pending','detected','rejected'):raise ValueError('Señal compartida no válida.')
    if not canonical_source(record.get('source_url','')) or not isinstance(record.get('quote'),str) or not 12<=len(record['quote'])<=900:raise ValueError('Falta evidencia válida.')
    if record.get('date_basis') not in ('document','provider_estimate','unknown','conflicting'):raise ValueError('Fecha no válida.')
    for field in ('published_at','event_at'):
        if record.get(field) and date_value(record[field])!=record[field]:raise ValueError('Fecha no válida.')
    if not isinstance(record.get('reviews',[]),list):raise ValueError('Historial no válido.')
    return record
