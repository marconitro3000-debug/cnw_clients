"""Conservative, deterministic extraction. Never infer identities from URL slugs."""
import json
import re
from urllib.parse import urljoin, urlparse, unquote
from bs4 import BeautifulSoup
from .domain import (FIRM, ROLE_CAPTURE, country_from, employee_range, evidence, identity,
                     infer_signals, is_linkedin, linkedin_url, normalized, now, safe_url)

CARD_SELECTOR = '[itemtype$="/Person"], .team-member, .team-card, .team__member, .person, [class*="team-member"], [class*="team__member"], [class*="team-card"], .block-single, article'
NAME_SELECTOR = '[itemprop="name"], h1, h2, h3, h4, [class*="team-card__name"]'

DIRECTORIES = {"linkedin.com", "bloomberg.com", "reuters.com", "ft.com", "morningstar.com",
    "crunchbase.com", "wikipedia.org", "fundinfo.com", "fundspeople.com", "citywire.com",
    "citywire.es", "citywire.co.uk", "rankia.com", "rankiapro.com", "finect.com",
    "efama.org", "thehedgefundjournal.com", "hedgefundjournal.com", "investmentweek.co.uk", "google.com", "facebook.com", "x.com", "youtube.com", "instagram.com"}

def domain_of(url):
    return (urlparse(url).hostname or "").lower().removeprefix("www.")

def corporate_domain(url):
    domain = domain_of(url)
    return domain and not any(domain == d or domain.endswith("." + d) for d in DIRECTORIES)

def human_name(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if not 4 <= len(value) <= 100 or any(c.isdigit() for c in value):
        return False
    words = value.split()
    if not 2 <= len(words) <= 6 or not all(any(c.isalpha() for c in w) for w in words):
        return False
    if any(c in value for c in "|:/@<>"):
        return False
    if re.search(r"\b(?:management|investment|gestora|equity|equities|team|equipo|fund|fondos|capital|officer|director|manager|contact|linkedin|about|home|asset|welcome|meet|nuestro|our|global|company|partners)\b", normalized(value)):
        return False
    return True

def type_is(node, kind):
    kinds = node.get("@type", [])
    if isinstance(kinds, str): kinds = [kinds]
    return any(str(k).split("/")[-1] == kind for k in kinds)

def jsonld_nodes(soup):
    result = []
    def walk(data):
        if isinstance(data, list):
            for item in data: walk(item)
        elif isinstance(data, dict):
            if "@type" in data: result.append(data)
            for key, value in data.items():
                if key not in ("@context",):
                    if isinstance(value, (dict, list)): walk(value)
    for script in soup.find_all("script", type="application/ld+json"):
        try: walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError): continue
    return result

def links_for_person(values):
    if isinstance(values, str): values = [values]
    found = list(dict.fromkeys(u for v in values if isinstance(v, str) and (u := linkedin_url(v))))
    return found[0] if len(found) == 1 else None

def firm_from_text(name, url, text, structured=None, observed_at=None):
    timestamp = observed_at or now()
    structured = structured or {}
    country = ""
    address = structured.get("address", {})
    if isinstance(address, list): address = address[0] if address else {}
    if isinstance(address, dict):
        raw_country = address.get("addressCountry", "")
        if isinstance(raw_country, dict): raw_country = raw_country.get("name", "")
        country = country_from(raw_country, structured=True)
    if not country:
        # Multiple countries, often marketing text, are not a verified location.
        country = country_from(text)
    lo, hi = employee_range(text)
    count = structured.get("numberOfEmployees")
    if isinstance(count, int) and count >= 0: lo = hi = count
    elif isinstance(count, dict):
        raw_lo = count.get("minValue", count.get("value"))
        raw_hi = count.get("maxValue", count.get("value"))
        try:
            if raw_lo is not None and raw_hi is not None:
                a, b = int(raw_lo), int(raw_hi)
                if 0 <= a <= b: lo, hi = a, b
        except (ValueError, TypeError): pass
    equity, analysis = infer_signals(text)
    data = {"name": name, "domain": domain_of(url), "country": country,
        "employees_min": lo, "employees_max": hi, "equity": equity, "analysis": analysis,
        "issues": [], "evidence": [evidence("company", name, url, name, timestamp)]}
    if country:
        quote = json.dumps(address, ensure_ascii=False) if address else excerpt(text, country)
        data["evidence"].append(evidence("country", country, url, quote, timestamp))
    if lo is not None and hi is not None:
        data["evidence"].append(evidence("employees", [lo, hi], url, json.dumps(count) if count else excerpt(text, "employees", "empleados", "plantilla"), timestamp))
    for key, val in (("equity", equity), ("analysis", analysis)):
        if val is not None:
            data["evidence"].append(evidence(key, val, url, excerpt(text, "equity", "equities", "renta variable", "stock", "acciones", "fundamental", "cuantitativo"), timestamp))
    return data

def excerpt(text, *terms):
    value = str(text)
    n = normalized(value)
    positions = [n.find(normalized(term)) for term in terms]
    idx = min((i for i in positions if i >= 0), default=0)
    return value[max(0, idx-120):idx+500]

def person_data(name, role, url, quote, linkedin=None, photo=None, issues=None, observed_at=None):
    timestamp = observed_at or now()
    data = {"name": name.strip(), "role": role.strip(), "linkedin_url": linkedin,
        "photo_url": photo if photo and safe_url(photo) else None, "issues": issues or [],
        "evidence": [evidence("name", name, url, quote, timestamp)]}
    if role: data["evidence"].append(evidence("role", role, url, quote, timestamp))
    if linkedin: data["evidence"].append(evidence("linkedin_url", linkedin, url, quote, timestamp))
    if data["photo_url"]: data["evidence"].append(evidence("photo_url", photo, url, quote, timestamp))
    return data

GENERIC_EMAIL = re.compile(r'^(?:info|contact|contacto|hello|support|admin|office|sales|comercial|marketing|press|prensa|investors|investorrelations|atencion)(?:[._-]|$)',re.I)

def public_email(value):
    value=unquote(str(value or '')).removeprefix('mailto:').split('?')[0].strip()
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&*+/=?^_~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',value): return None
    return value

def public_phone(value):
    value=unquote(str(value or '')).removeprefix('tel:').strip()
    value=re.split(r'[;#]',value)[0]
    if not re.fullmatch(r'[+0-9 ()\-./]+',value): return None
    if not 7<=len(re.sub(r'\D','',value))<=15: return None
    return value

def attach_public_channels(person,scope,url,observed_at=None,structured=None):
    stamp=observed_at or now();structured=structured or {}
    emails=[];phones=[]
    emails.extend([structured.get('email')])
    phones.extend([structured.get('telephone')])
    points=structured.get('contactPoint',[])
    if isinstance(points,dict): points=[points]
    for point in points if isinstance(points,list) else []:
        if isinstance(point,dict): emails.append(point.get('email'));phones.append(point.get('telephone'))
    if scope is not None:
        emails.extend(a.get('href') for a in scope.select('a[href^="mailto:"]'))
        phones.extend(a.get('href') for a in scope.select('a[href^="tel:"]'))
        phones.extend(re.findall(r'(?:tel[eé]fono|tel[eé]phone|phone|m[oó]vil|mobile|tel)\s*[:.]?\s*(\+?[0-9][0-9 ()\-./]{6,22}[0-9])',scope.get_text(' ',strip=True),re.I))
        # Visible addresses are accepted only inside a card with one named person.
        emails.extend(re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',scope.get_text(' ',strip=True)))
    emails=list(dict.fromkeys(v for value in emails if (v:=public_email(value)) and not GENERIC_EMAIL.search(v.split('@')[0])))
    phones=list(dict.fromkeys(v for value in phones if (v:=public_phone(value))))
    if len(emails)==1:
        person['email']=emails[0];person['email_status']='public_unverified'
        person['evidence'].append(evidence('email',emails[0],url,emails[0],stamp))
    elif len(emails)>1: person['issues'].append('conflict:email')
    if phones:
        person['phones']=[{'number':value,'type':'public','status':'public_unverified','source':url,'observed_at':stamp} for value in phones]
        person['evidence'].extend(evidence('phone',value,url,value,stamp) for value in phones)
    return person

def person_photo(scope,url,name):
    """A named image or sole portrait inside a card for exactly one person."""
    images=[]
    for img in scope.find_all('img'):
        source=img.get('data-src') or img.get('data-lazy-src') or img.get('src')
        target=urljoin(url,source) if source else ''
        if not target or not safe_url(target): continue
        alt=img.get('alt','')
        if identity(alt)==identity(name) or img.get('itemprop')=='image': return target
        marker=' '.join([alt,target,' '.join(img.get('class',[]))])
        if re.search(r'(?:logo|icon|placeholder|pixel|tracking|flag|banner|\.svg(?:\?|$))',marker,re.I): continue
        images.append(target)
    return images[0] if len(images)==1 else None


def person_links(html,url,name):
    soup=BeautifulSoup(html,'html.parser');links=[]
    def add(anchor):
        target=urljoin(url,anchor['href']).split('#')[0]
        if safe_url(target) and domain_of(target)==domain_of(url) and target!=url and target not in links: links.append(target)
    for anchor in soup.find_all('a',href=True):
        if identity(anchor.get_text(' ',strip=True))==identity(name): add(anchor)
    for card in soup.select(CARD_SELECTOR):
        names={identity(n.get_text(' ',strip=True)) for n in card.select(NAME_SELECTOR) if human_name(n.get_text(' ',strip=True))}
        if names!={identity(name)}: continue
        for anchor in card.find_all('a',href=True):
            if re.search(r'(?:ficha|biograf|bio|perfil|profile|details|detalle|ver)',anchor.get_text(' ',strip=True),re.I): add(anchor)
    return links[:3]


def extract_person_page(html,url,person,observed_at=None):
    soup=BeautifulSoup(html,'html.parser')
    for tag in soup(['script','style','nav','footer']): tag.decompose()
    headings=[h.get_text(' ',strip=True) for h in soup.select('h1,h2,[itemprop="name"]')]
    if identity(person['name']) not in {identity(h) for h in headings}: return None
    # Do not treat a team directory or an article mentioning several people as a biography.
    named=[h for h in headings if human_name(h)]
    if any(identity(n)!=identity(person['name']) for n in named): return None
    card=soup.find('main') or soup.find('article') or soup.body or soup
    text=card.get_text(' ',strip=True)
    match=ROLE_CAPTURE.search(text)
    data=person_data(person['name'],match.group(0) if match else '',url,text,links_for_person([urljoin(url,a['href']) for a in card.find_all('a',href=True)]),observed_at=observed_at)
    photo=person_photo(card,url,person['name'])
    if photo:
        data['photo_url']=photo;data['evidence'].append(evidence('photo_url',photo,url,person['name'],observed_at))
    return attach_public_channels(data,card,url,observed_at)

def name_from_title(title):
    clean = re.sub(r"\s*[|–-]\s*LinkedIn.*$", "", title, flags=re.I)
    first = re.split(r"\s+(?:[-–—|])\s+", clean)[0].strip()
    first = re.sub(r",?\s+(?:CFA|PhD|CAIA|MBA)\b.*$", "", first).strip()
    return first if human_name(first) else None

def result_person(result, firm):
    url = result.get("url", "")
    title, content = result.get("title", ""), result.get("content", "")
    profile = linkedin_url(url)
    if not profile:
        return None
    name = name_from_title(title)
    if not name: return None
    text = title + "\n" + content
    key = identity(firm["name"])
    if not key or key not in identity(text):
        return None
    # A company named Gestora is not evidence of a portfolio-manager role.
    role_title_text = re.sub(re.escape(firm["name"]), "", title, flags=re.I)
    role_body_text = re.sub(re.escape(firm["name"]), "", content, flags=re.I)
    role_title = ROLE_CAPTURE.search(role_title_text)
    role_body = ROLE_CAPTURE.search(role_body_text)
    role_match = role_title or role_body
    role = role_match.group(0) if role_match else ""
    issues = []
    if not role_title: issues.append("role_unverified")
    # Title association is stronger than a company name in career history.
    title_association = key in identity(title)
    current_association = re.search(r"(?:at|en|de)\s+" + re.escape(normalized(firm["name"])), normalized(content))
    if not title_association and not current_association:
        issues.append("association_unverified")
    if re.search(r"\b(?:former|previous|ex-|anterior|retired)\b", normalized(text)):
        issues.append("role_unverified")
    return person_data(name, role, url, text, profile, issues=issues, observed_at=result.get("observed_at"))

def valid_firm_name(name):
    text = normalized(name)
    if len(name) > 120 or len(name.strip()) < 3: return False
    if re.search(r'\b(?:report|informe|association|asociacion|federation|federacion|trusted partner|your trusted|welcome|bienvenido|market outlook|industry overview|asset management in europe|our expertise)\b', text): return False
    if text in ('asset management','investment management','fund management','gestora'): return False
    # Article, ranking and directory headlines are not companies.
    if ':' in name or '?' in name or re.search(r'\btop \d+|\b\d+ (?:best|mejores|meilleures?)\b', text): return False
    if re.search(r'\b(?:insights?|the rise of|the future of|ranking|rankings|news|noticias|guide|guia|how to|como elegir|the best|los mejores|incontournables|les boutiques|las mejores|lista de|list of|managers by|que es|what is)\b', text): return False
    if re.fullmatch(r'(?:gestoras?|sociedad(?:es)? gestoras?) de fondos de inversion.*', text): return False
    if re.search(r'\b(?:trends?|tendencias|competitors|competidores|alternatives|outlook|about)\b|^(?:19|20)\d\d\b|\b(?:19|20)\d\d$', text) or name.count(',') >= 2: return False
    # A name made only of generic industry words names no company.
    if not re.sub(r'\b(?:the|top|specialist|leading|independent|boutique|global|european|asset|assets|investment|investments|fund|funds|management|manager|managers|gestora|gestoras|de|fondos|equity|equities|and|&)\b|[^a-z0-9]', '', text): return False
    return True

def result_firm(result):
    url = result.get("url", "")
    if not safe_url(url) or not corporate_domain(url):
        return None
    text = str(result.get("title", "")) + " " + str(result.get("content", ""))
    if not re.search(FIRM, normalized(text)):
        return None
    title = result.get("title", "")
    pieces = [p.strip() for p in re.split(r"\s*[|–—]\s*|\s+-\s+", title) if p.strip()]
    candidates = [p for p in pieces if re.search(FIRM + r"|\b(?:capital|investments|partners|sg iic|sgiic)\b", normalized(p)) and len(p) < 120]
    if not candidates: return None
    candidates = [c for c in candidates if valid_firm_name(c)]
    if not candidates: return None
    name = min(candidates, key=len)
    if normalized(name) in ("asset management", "investment management", "fund management", "gestora"):
        return None
    return firm_from_text(name, url, text, observed_at=result.get("observed_at"))

def extract_page(html, url, expected_firm=None, observed_at=None):
    """Returns one company plus biographies explicitly associated with that company."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = jsonld_nodes(soup)
    by_id = {n.get("@id"): n for n in nodes if n.get("@id")}
    organizations = [n for n in nodes if type_is(n, "Organization") or type_is(n, "FinancialService")]
    org = next((n for n in organizations if n.get("name") and re.search(FIRM + r"|\b(?:capital|investments|partners)\b", normalized(n.get("name", "")))), organizations[0] if len(organizations) == 1 else {})
    for tag in soup(["script", "style", "nav", "footer"]): tag.decompose()
    text = soup.get_text(" ", strip=True)[:120000]
    name = (expected_firm or {}).get("name") or org.get("name")
    if not name:
        site = soup.find("meta", property="og:site_name")
        if site: name = site.get("content")
    if not name:
        title = soup.title.get_text() if soup.title else ""
        seed = result_firm({"url": url, "title": title, "content": text})
        name = seed["name"] if seed else None
    if not name or (not expected_firm and not re.search(FIRM, normalized(text + " " + json.dumps(org)))):
        return {"firm": None, "people": []}
    if expected_firm and domain_of(url) != expected_firm.get("domain", ""):
        return {"firm": None, "people": []}
    firm = firm_from_text(str(name), url, text + " " + str(org.get("description", "")), org, observed_at)
    people = []
    for node in nodes:
        if not type_is(node, "Person") or not human_name(node.get("name", "")): continue
        works = node.get("worksFor", {})
        if isinstance(works, list): works = works[0] if works else {}
        if isinstance(works, dict):
            works = by_id.get(works.get("@id"), works)
            employer = works.get("name")
        else: employer = works
        if employer and identity(employer) not in (identity(name), identity(org.get("name", ""))):
            continue
        # Person JSON-LD needs worksFor or a current team page, not authorship of a blog.
        team_page = bool(re.search(r"(?:team|equipo|people|leadership|about|nosotros)", urlparse(url).path, re.I))
        if not employer and not team_page: continue
        role = str(node.get("jobTitle", ""))
        if not ROLE_CAPTURE.search(role): continue
        photo = node.get("image")
        if isinstance(photo, dict): photo = photo.get("url", photo.get("contentUrl"))
        photo = urljoin(url, photo) if isinstance(photo, str) else None
        profiles = node.get("sameAs", [])
        if isinstance(profiles, str): profiles = [profiles]
        if not isinstance(profiles, list): profiles = []
        profiles = profiles + ([node["url"]] if isinstance(node.get("url"), str) else [])
        people.append(attach_public_channels(person_data(node["name"], role, url, json.dumps(node, ensure_ascii=False),
            links_for_person(profiles), photo, observed_at=observed_at),None,url,observed_at,node))
    cards = soup.select(CARD_SELECTOR)
    for card in cards:
        names = [h.get_text(" ", strip=True) for h in card.select(NAME_SELECTOR)]
        names = list(dict.fromkeys(n for n in names if human_name(n)))
        if len(names) != 1: continue
        person_name = names[0]
        local_text = card.get_text(" ", strip=True)
        match = ROLE_CAPTURE.search(local_text)
        if not match: continue
        profile = links_for_person([urljoin(url, a.get("href", "")) for a in card.find_all("a", href=True)])
        photo = person_photo(card,url,person_name)
        people.append(attach_public_channels(person_data(person_name, match.group(0), url, local_text, profile, photo, observed_at=observed_at),card,url,observed_at))
    # Keep every observation, then database merging preserves conflicting evidence.
    return {"firm": firm, "people": people}

def team_links(html, url):
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for anchor in soup.find_all("a", href=True):
        target = urljoin(url, anchor["href"]).split("#")[0]
        label = anchor.get_text(" ", strip=True) + " " + urlparse(target).path
        if domain_of(target) == domain_of(url) and not is_linkedin(target) and re.search(r"\b(?:team|equipo|people|leadership|nosotros|about)\b", label, re.I) and target not in result:
            result.append(target)
    return result[:2]
