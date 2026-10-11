"""Duplicate firms and people. Obvious cases are merged automatically; ambiguous people are left to the local model.
Merged identifiers keep an alias so shared copies of the project map to the surviving record."""
import itertools
import json
import re
from .domain import identity, now

LEGAL = r'\b(?:limited|ltd|llp|plc|ag|sa|s a|sl|sgiic|sgii|gmbh|kg|nv|bv|ab|as|spa|srl|sas|lp|llc|inc|group|holdings?|international)\b'
TITLES = {'cfa', 'phd', 'dr', 'mfia', 'cesga', 'cfa®', 'mba', 'cqf', 'frm', 'caia'}

def firm_key(name):
    return ' '.join(re.sub(LEGAL, ' ', identity(name)).split())

def own_domain(name, domain):
    """A firm's own site usually contains a distinctive word of its name; directories and news sites do not."""
    words = [w for w in identity(name).split() if len(w) >= 4 and w not in ('asset', 'management', 'investment', 'investments', 'capital', 'partners', 'gestion', 'gestora', 'fondos', 'fund', 'funds')]
    host = (domain or '').replace('-', '').replace('.', ' ')
    return any(w in host for w in words)

def person_tokens(name):
    name = re.sub(r'\(.*?\)', ' ', str(name or ''))
    head, _, tail = name.partition(',')
    # "SURNAME, Given Names" from regulator registers.
    if tail and head.strip().isupper() and not tail.strip().isupper(): name = tail + ' ' + head
    else: name = head
    return [w for w in identity(name.replace('-', ' ')).split() if len(w) > 1 and w not in TITLES]

def same_name(a, b):
    return person_tokens(a) == person_tokens(b) and len(person_tokens(a)) >= 2

def similar_name(a, b):
    ta, tb = person_tokens(a), person_tokens(b)
    if len(ta) < 2 or len(tb) < 2 or ta[-1] != tb[-1] and ta[0] != tb[0]: return False
    sa, sb = set(ta), set(tb)
    # Same surname and a shared or abbreviated given name ("Ed Bell" / "Edward Bell").
    return sa <= sb or sb <= sa or (ta[-1] == tb[-1] and (ta[0].startswith(tb[0]) or tb[0].startswith(ta[0])))

def remove_shared(crm, kind, key):
    path = crm.directory / kind / (key + '.json')
    if path.exists(): path.unlink()
    crm.write_cache.pop(str(path), None)


def merge_firms(crm):
    """Merge copies of the same firm saved under a directory or news domain into the firm's own site."""
    db = crm.db
    with db.connect() as con:
        firms = [dict(r) for r in con.execute('SELECT id,uuid,name,domain,data FROM firms')]
        counts = {r[0]: r[1] for r in con.execute('SELECT firm_id,count(*) FROM contacts GROUP BY firm_id')}
    groups = {}
    for f in firms: groups.setdefault(firm_key(f['name']), []).append(f)
    merged = []
    for key, group in groups.items():
        if len(group) < 2 or not key: continue
        own = [f for f in group if own_domain(f['name'], f['domain'])]
        others = [f for f in group if f not in own]
        # Two different firms can share a generic name; only third-party copies of a firm with its own site are merged.
        if len(own) != 1 or not others: continue
        winner = own[0]
        for loser in others:
            absorb_firm(crm, winner, loser)
            merged.append((winner['name'], loser['domain'], counts.get(loser['id'], 0)))
    return merged

def absorb_firm(crm, winner, loser):
    db = crm.db
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        data, extra = json.loads(winner['data']), json.loads(loser['data'])
        evidence = data.get('evidence', [])
        for item in extra.get('evidence', []):
            if item not in evidence: evidence.append(item)
        data['evidence'] = evidence
        for field in ('country', 'employees_min', 'employees_max', 'equity', 'analysis'):
            if data.get(field) is None and extra.get(field) is not None: data[field] = extra[field]
        con.execute('UPDATE firms SET data=?,updated_at=? WHERE id=?', (json.dumps(data), now(), winner['id']))
        con.execute('UPDATE contacts SET firm_id=? WHERE firm_id=?', (winner['id'], loser['id']))
        for row in con.execute('SELECT uuid,data FROM business_signals WHERE firm_uuid=?', (loser['uuid'],)).fetchall():
            signal = {**json.loads(row[1]), 'firm_uuid': winner['uuid']}
            con.execute('UPDATE business_signals SET firm_uuid=?,data=? WHERE uuid=?', (winner['uuid'], json.dumps(signal, ensure_ascii=False), row[0]))
        con.execute('DELETE FROM firm_segments WHERE firm_uuid=?', (loser['uuid'],))
        con.execute('DELETE FROM firms WHERE id=?', (loser['id'],))
        con.execute('INSERT OR REPLACE INTO shared_aliases VALUES(?,?)', (loser['uuid'], winner['uuid']))
    remove_shared(crm, 'firms', loser['uuid'])
    remove_shared(crm, 'segments', loser['uuid'])
    winner['data'] = json.dumps(data)


def candidate_pairs(contacts):
    """Pairs that may be the same person: same firm with a similar name, or anywhere with an identical full name."""
    sure, unsure = [], []
    for a, b in itertools.combinations(contacts, 2):
        la, lb = a.get('linkedin_url'), b.get('linkedin_url')
        if la and lb and la != lb: continue  # two distinct LinkedIn profiles are two people
        if same_name(a['name'], b['name']) and (a['firm_id'] == b['firm_id'] or la and la == lb): sure.append((a, b))
        elif a['firm_id'] == b['firm_id'] and similar_name(a['name'], b['name']): unsure.append((a, b))
        elif same_name(a['name'], b['name']): unsure.append((a, b))
    return sure, unsure

def pair_key(a, b):
    return '|'.join(sorted((a['uuid'], b['uuid'])))

def merge_contacts(crm, a, b):
    """Keep the record with LinkedIn and history; move everything else onto it."""
    winner, loser = sorted((a, b), key=lambda c: (not c.get('linkedin_url'), -c.get('interaction_count', 0), c['id']))
    db = crm.db
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        rows = {r['id']: r for r in con.execute('SELECT * FROM contacts WHERE id IN (?,?)', (winner['id'], loser['id']))}
        if len(rows) < 2: return None
        data, extra = json.loads(rows[winner['id']]['data']), json.loads(rows[loser['id']]['data'])
        for item in extra.get('evidence', []):
            if item not in data.setdefault('evidence', []): data['evidence'].append(item)
        for field in ('role', 'photo_url', 'linkedin_url'):
            if not data.get(field) and extra.get(field): data[field] = extra[field]
        data['issues'] = [i for i in dict.fromkeys(data.get('issues', []) + extra.get('issues', [])) if i != 'possible_duplicate']
        link = rows[winner['id']]['linkedin_url'] or rows[loser['id']]['linkedin_url']
        con.execute('UPDATE contacts SET linkedin_url=NULL WHERE id=?', (loser['id'],))  # frees the profile link for the survivor
        con.execute('UPDATE contacts SET data=?,linkedin_url=?,updated_at=? WHERE id=?', (json.dumps(data), link, now(), winner['id']))
        meta = {r[0]: json.loads(r[1]) for r in con.execute('SELECT contact_id,data FROM contact_crm WHERE contact_id IN (?,?)', (winner['id'], loser['id']))}
        kept, other = meta.get(winner['id'], {}), meta.get(loser['id'], {})
        combined = {**other, **{k: v for k, v in kept.items() if v not in (None, '', [], {})}}
        phones = {p.get('number'): p for p in other.get('phones', []) + kept.get('phones', [])}
        if phones: combined['phones'] = list(phones.values())
        con.execute('INSERT OR REPLACE INTO contact_crm VALUES(?,?)', (winner['id'], json.dumps(combined, ensure_ascii=False, sort_keys=True)))
        con.execute('DELETE FROM contact_crm WHERE contact_id=?', (loser['id'],))
        for row in con.execute('SELECT uuid,data FROM interactions WHERE contact_uuid=?', (loser['uuid'],)).fetchall():
            event = {**json.loads(row[1]), 'contact_uuid': winner['uuid']}
            con.execute('UPDATE interactions SET contact_uuid=?,data=? WHERE uuid=?', (winner['uuid'], json.dumps(event, ensure_ascii=False, sort_keys=True), row[0]))
        for row in con.execute('SELECT run_uuid,data FROM observations WHERE contact_uuid=?', (loser['uuid'],)).fetchall():
            observation = {**json.loads(row[1]), 'contact_uuid': winner['uuid']}
            con.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?)', (winner['uuid'], row[0], json.dumps(observation, ensure_ascii=False, sort_keys=True)))
            remove_shared(crm, 'observations', loser['uuid'] + '_' + row[0])
        con.execute('DELETE FROM observations WHERE contact_uuid=?', (loser['uuid'],))
        con.execute('DELETE FROM contacts WHERE id=?', (loser['id'],))
        con.execute('INSERT OR REPLACE INTO shared_aliases VALUES(?,?)', (loser['uuid'], winner['uuid']))
    remove_shared(crm, 'contacts', loser['uuid'])
    return winner, loser

def merge_obvious(crm):
    """Runs without the model: duplicate firms and identical names at the same firm or LinkedIn profile."""
    firms = merge_firms(crm)
    people = []
    while True:
        sure, _ = candidate_pairs(crm.db.contacts())
        if not sure: break
        result = merge_contacts(crm, *sure[0])
        if not result: break
        people.append(result[1]['name'])
    if firms or people: crm.export_shared()
    return firms, people
