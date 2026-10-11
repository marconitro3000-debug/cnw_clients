"""Firm subsectors inferred from public text already collected. Every label cites the sentence that supports it."""
import json
import re
import uuid
from .domain import normalized, now

# Order breaks ties: the most specific investment styles come first.
SEGMENTS = {
    'quant': ('Cuantitativa y quantamental', 'Modelos sistemáticos, factores o análisis de datos',
        r'\b(?:quant\w*|quantamental|systematic|sistematic\w*|factor (?:investing|models?|based)|machine learning|data[- ]driven|algorithm\w*|algoritm\w*|python)\b'),
    'hedge_fund': ('Hedge funds y retorno absoluto', 'Long/short, event-driven, activismo o retorno absoluto',
        r'\b(?:hedge funds?|long[ /-]short|absolute return|retorno absoluto|event[ -]driven|activis[tm]\w*|market neutral|special situations|situaciones especiales)\b'),
    'boutique_equity': ('Boutique de renta variable', 'Selección de acciones, value, growth o small caps',
        r'\b(?:stock[ -]?picking|stock selection|seleccion de (?:acciones|valores)|value investing|inversion en valor|value investors?|growth investing|small[ -]?(?:and mid[ -]?)?caps?|mid[ -]?caps?|equity research|bottom[ -]up|fundamental (?:analysis|research)|analisis fundamental|long[ -]only|concentrated portfolio|cartera concentrada)\b'),
    'thematic': ('Temática y sostenible', 'ESG, impacto o especialistas sectoriales',
        r'\b(?:esg|sustainab\w*|sostenib\w*|impact investing|inversion de impacto|thematic|tematic\w*|climate|healthcare|biotech\w*|technology funds?)\b'),
    'wealth': ('Banca privada y family office', 'Gestión patrimonial para clientes privados',
        r'\b(?:wealth management|wealth managers?|private (?:banking|clients?|wealth)|banca privada|family offices?|multi[- ]family|high net worth|hnwis?|gestion patrimonial|patrimonios?)\b'),
    'multi_asset': ('Multiactivo y generalista', 'Asignación de activos, perfiles mixtos o fondos de fondos',
        r'\b(?:multi[- ]asset|multiactivo|asset allocation|asignacion de activos|balanced (?:funds?|portfolios?)|fondos? mixtos?|fund of funds|fondos? de fondos)\b'),
    'private_markets': ('Mercados privados', 'Private equity, venture, inmobiliario o deuda privada',
        r'\b(?:private equity|venture capital|capital riesgo|real estate|inmobiliari\w*|private debt|deuda privada|infrastructure|infraestructuras?)\b'),
}
UNCLASSIFIED = 'unclassified'
LABELS = {k: v[0] for k, v in SEGMENTS.items()} | {UNCLASSIFIED: 'Sin clasificar'}

def sentences(text):
    for part in re.split(r'(?<=[.!?])\s+|\n+|\s\|\s', str(text or '')):
        part = ' '.join(part.split())
        if 4 <= len(part) <= 600: yield part

def classify(texts, equity=None):
    """texts: (text, url) pairs. Returns the main segment, other matches and quoted evidence."""
    found = {}
    seen = set()
    for text, url in texts:
        for sentence in sentences(text):
            clean = normalized(sentence)
            if clean in seen: continue
            seen.add(clean)
            for key, (_, _, pattern) in SEGMENTS.items():
                if re.search(pattern, clean): found.setdefault(key, []).append({'segment': key, 'quote': sentence[:300], 'url': url})
    ranked = sorted(found, key=lambda k: (-len(found[k]), list(SEGMENTS).index(k)))
    # Mentioning private markets does not make a listed-equity manager a private-markets firm.
    if equity is True and len(ranked) > 1 and ranked[0] == 'private_markets': ranked = ranked[1:] + ['private_markets']
    segment = ranked[0] if ranked else UNCLASSIFIED
    return {'segment': segment, 'tags': ranked[1:], 'evidence': [e for k in ranked for e in found[k][:2]], 'sources': len(found.get(segment, []))}

def ensure_table(con):
    con.execute('CREATE TABLE IF NOT EXISTS firm_segments (firm_uuid TEXT PRIMARY KEY, data TEXT NOT NULL)')

def overrides(crm):
    with crm.db.connect() as con:
        ensure_table(con)
        return {r[0]: json.loads(r[1]) for r in con.execute('SELECT firm_uuid,data FROM firm_segments')}

def firm_segments(crm, firm_ids=None):
    """Classify firms using their own evidence, their contacts' evidence and roles, and their news signals."""
    with crm.db.connect() as con:
        firms = [dict(r) for r in con.execute('SELECT id,uuid,data FROM firms')]
        contacts = [dict(r) for r in con.execute('SELECT firm_id,data FROM contacts')]
        signals = [json.loads(r[0]) for r in con.execute('SELECT data FROM business_signals')]
    manual = overrides(crm)
    texts = {}
    for f in firms:
        data = json.loads(f['data'])
        texts[f['id']] = [(e.get('quote', ''), e.get('url', '')) for e in data.get('evidence', [])]
    for c in contacts:
        data = json.loads(c['data'])
        texts.setdefault(c['firm_id'], []).extend([(data.get('role', ''), '')] + [(e.get('quote', ''), e.get('url', '')) for e in data.get('evidence', [])])
    by_uuid = {f['uuid']: f['id'] for f in firms}
    for s in signals:
        if s.get('review') != 'rejected' and s.get('firm_uuid') in by_uuid: texts[by_uuid[s['firm_uuid']]].append((s.get('quote', ''), s.get('source_url', '')))
    result = {}
    for f in firms:
        if firm_ids is not None and f['id'] not in firm_ids: continue
        info = classify(texts.get(f['id'], []), json.loads(f['data']).get('equity'))
        override = manual.get(f['uuid'])
        if override and override.get('segment') in LABELS:
            info = {**info, 'automatic': info['segment'], 'segment': override['segment'], 'manual': override}
        result[f['id']] = {**info, 'label': LABELS[info['segment']]}
    return result

def set_segment(crm, firm_id, segment):
    firm = crm.db.firm(firm_id)
    if not firm: raise LookupError('Gestora no encontrada.')
    if segment is not None and segment not in LABELS: raise ValueError('Subsector no válido.')
    with crm.db.connect() as con:
        ensure_table(con)
        if segment is None: con.execute('DELETE FROM firm_segments WHERE firm_uuid=?', (firm['uuid'],))
        else: con.execute('INSERT OR REPLACE INTO firm_segments VALUES(?,?)', (firm['uuid'], json.dumps({'uuid': firm['uuid'], 'firm_uuid': firm['uuid'], 'segment': segment, 'author': crm.setting('actor', 'Marco'), 'updated_at': now()}, ensure_ascii=False, sort_keys=True)))
    crm.export_shared()

def validate_shared_segment(record):
    uuid.UUID(record['firm_uuid'])
    if record.get('segment') not in LABELS: raise ValueError('Subsector compartido no válido.')
    return record

def groups(crm):
    contacts = crm.db.contacts()
    segments = firm_segments(crm)
    with crm.db.connect() as con: firms = {r['id']: dict(r) for r in con.execute('SELECT id,name,domain,data FROM firms')}
    people = {}
    from .autopilot import is_junk, doubtful_firm
    for c in contacts:
        if not is_junk(c): people.setdefault(c['firm_id'], []).append(c)
    result = {key: {'key': key, 'label': LABELS[key], 'description': SEGMENTS[key][1] if key in SEGMENTS else 'Sin texto público suficiente para clasificar', 'firms': []} for key in LABELS}
    for fid, info in segments.items():
        team = people.get(fid, [])
        if not team: continue
        f = firms[fid]
        doubtful = doubtful_firm(f['name']) or any((c.get('quality') or {}).get('status') == 'doubtful_firm' for c in team)
        result[info['segment']]['firms'].append({'id': fid, 'name': f['name'], 'domain': f['domain'], 'country': json.loads(f['data']).get('country', ''), 'doubtful_name': doubtful,
            **{k: info.get(k) for k in ('segment', 'label', 'tags', 'evidence', 'sources', 'automatic', 'manual')},
            'contacts': len(team), 'qualified': sum(c['status'] == 'qualified' for c in team), 'best_score': max(c['score'] for c in team),
            'best_opportunity': max(c['opportunity_score'] for c in team), 'targets': sum(c['opportunity_status'] == 'target' for c in team),
            'unwilling': sum(c['opportunity_status'] == 'unwilling' for c in team), 'contacted': sum(c['blocked'] for c in team),
            'people': [{k: c.get(k) for k in ('id', 'name', 'role', 'linkedin_url', 'score', 'status', 'opportunity_score', 'opportunity_status', 'stage')}
                for c in sorted(team, key=lambda c: (c['status'] != 'qualified', -c['opportunity_score'], -c['score'], not c.get('linkedin_url'), normalized(c['name'])))]})
    for g in result.values():
        g['firms'].sort(key=lambda f: (f['doubtful_name'], -f['best_opportunity'], -f['best_score'], normalized(f['name'])))
        g.update(firm_count=len(g['firms']), contact_count=sum(f['contacts'] for f in g['firms']), qualified=sum(f['qualified'] for f in g['firms']),
                 targets=sum(f['targets'] for f in g['firms']), unwilling=sum(f['unwilling'] for f in g['firms']))
    return [g for g in result.values() if g['firm_count']]
