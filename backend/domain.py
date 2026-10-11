import ipaddress
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote

EUROPE = {
    "España": ("spain", "espana", "madrid", "barcelona"),
    "Francia": ("france", "francia", "paris"),
    "Alemania": ("germany", "alemania", "deutschland", "frankfurt"),
    "Reino Unido": ("united kingdom", "reino unido", "london", "londres", " uk "),
    "Irlanda": ("ireland", "irlanda", "dublin"),
    "Italia": ("italy", "italia", "milan", "milano"),
    "Portugal": ("portugal", "lisbon", "lisboa"),
    "Suiza": ("switzerland", "suiza", "suisse", "zurich", "geneva"),
    "Países Bajos": ("netherlands", "paises bajos", "amsterdam"),
    "Luxemburgo": ("luxembourg", "luxemburgo"),
    "Bélgica": ("belgium", "belgica", "brussels", "bruselas"),
    "Austria": ("austria", "vienna"),
    "Suecia": ("sweden", "suecia", "stockholm"),
    "Dinamarca": ("denmark", "dinamarca", "copenhagen"),
    "Noruega": ("norway", "noruega", "oslo"),
    "Finlandia": ("finland", "finlandia", "helsinki"),
    "Polonia": ("poland", "polonia", "warsaw"),
    "Grecia": ("greece", "grecia"),
    "República Checa": ("czechia", "czech republic", "republica checa", "prague"),
    "Hungría": ("hungary", "hungria"),
    "Islandia": ("iceland", "islandia"),
    "Estonia": ("estonia",), "Letonia": ("latvia", "letonia"),
    "Lituania": ("lithuania", "lituania"), "Malta": ("malta",),
    "Chipre": ("cyprus", "chipre"), "Rumanía": ("romania", "rumania"),
    "Bulgaria": ("bulgaria",), "Croacia": ("croatia", "croacia"),
    "Eslovenia": ("slovenia", "eslovenia"), "Eslovaquia": ("slovakia", "eslovaquia"),
    "Liechtenstein": ("liechtenstein",), "Andorra": ("andorra",),
    "Mónaco": ("monaco",), "San Marino": ("san marino",),
    "Serbia": ("serbia",), "Ucrania": ("ukraine", "ucrania"),
    "Albania": ("albania",), "Montenegro": ("montenegro",),
    "Macedonia del Norte": ("north macedonia", "macedonia del norte"),
    "Bosnia y Herzegovina": ("bosnia",), "Kosovo": ("kosovo",),
    "Moldavia": ("moldova", "moldavia"),
}
COUNTRY_CODES = dict(zip(
    "ES FR DE GB IE IT PT CH NL LU BE AT SE DK NO FI PL GR CZ HU IS EE LV LT MT CY RO BG HR SI SK LI AD MC SM RS UA AL ME MK BA XK MD".split(),
    EUROPE.keys(),
))
OTHER_COUNTRIES = {
    "Estados Unidos": ("united states", "estados unidos", "new york", " usa "),
    "Canadá": ("canada",), "Australia": ("australia",), "Singapur": ("singapore", "singapur"),
    "China": ("china",), "India": ("india",), "Brasil": ("brazil", "brasil"),
}
DECISOR = r"\b(?:cio|chief investment officer|investment director|director(?:a)? (?:de )?inversiones|head of (?:equities|equity|investments?|investment management)|responsable (?:de )?(?:renta variable|inversiones)|(?:managing |founding )?partner|socio(?:a)?(?: director(?:a)?)?)\b"
MANAGER = r"\b(?:portfolio manager|fund manager|investment manager|gestor(?:a)?(?: de (?:fondos|carteras))?)\b"
# At a 5-200 person boutique the founder, CEO or head of research usually signs for research tools.
LEADER = r"\b(?:founder|co-?founder|founding|fundador(?:a)?|cofundador(?:a)?|ceo|chief executive|consejer[oa] delegad[oa]|director(?:a)? general|managing director|chair(?:man|woman|person)?|presidente?a?|executive board|comite (?:ejecutivo|de direccion)|head of (?:equity |investment |quantitative |quant )?research|director(?:a)? de (?:analisis|research)|research director|head of (?:\w+ ){0,2}(?:investment strateg\w*|portfolio management|hedge funds?)|co-?manager)\b"
NOT_BUYER = r"\b(?:sales|business development|relationship manager|consultant|support|marketing|client service|investor relations|distribution|desarrollo de negocio|comercial)\b"
ANALYST = r"\b(?:equity analyst|investment analyst|analista(?: de inversiones| de renta variable)?)\b"
EQUITY = r"\b(?:renta variable|equities|(?:public |listed |global |european |long.?short )?equity|stock(?:s| selection| picking)?)\b"
ANALYSIS = r"\b(?:stock selection|stock picking|equity research|seleccion de acciones|analisis (?:de acciones|fundamental|cuantitativo)|fundamental analysis|quantitative (?:analysis|research)|factor investing)\b"
FIRM = r"\b(?:asset management|asset manager|gestora|gestion de (?:activos|fondos)|investment management|fund management)\b"
ROLE_RE = re.compile(f"(?:{DECISOR}|{MANAGER}|{ANALYST})", re.I)
ROLE_CAPTURE = re.compile(
    r"\b(?:chief investment officer|chief executive officer|head of (?:equities|equity|investments?|investment management)|investment director|director(?:a)? (?:de )?inversiones|responsable (?:de )?(?:renta variable|inversiones)|portfolio manager|fund manager|investment manager|equity analyst|investment analyst|analista(?: de inversiones| de renta variable)?|gestor(?:a)?(?: de (?:fondos|carteras))?|(?:managing |founding )?partner|socio(?:a)?(?: director(?:a)?)?|CIO)\b",
    re.I,
)

def now():
    return datetime.now(timezone.utc).isoformat()

def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text or "").lower()) if not unicodedata.combining(c)).strip()

def identity(text):
    return re.sub(r"[^a-z0-9]+", " ", normalized(text)).strip()

def is_linkedin(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "linkedin.com" or host.endswith(".linkedin.com")

def safe_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 80, 443):
            return False
        host = parsed.hostname.lower()
        if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except (ValueError, TypeError):
        return False

def linkedin_url(url):
    try:
        if not safe_url(url) or not is_linkedin(url):
            return None
        match = re.fullmatch(r"/in/([^/]+)/?", urlparse(url).path)
        if not match or not re.fullmatch(r"[\w.-]+", unquote(match.group(1))):
            return None
        return "https://www.linkedin.com/in/" + unquote(match.group(1)).lower().rstrip("/") + "/"
    except (ValueError, TypeError):
        return None

def country_from(text, structured=False):
    value = str(text or "").strip()
    if structured and value.upper() in COUNTRY_CODES:
        return COUNTRY_CODES[value.upper()]
    hay = " " + normalized(value) + " "
    found = []
    for country, aliases in {**EUROPE, **OTHER_COUNTRIES}.items():
        if any(re.search(r"(?<!\w)" + re.escape(normalized(a).strip()) + r"(?!\w)", hay) for a in (country, *aliases)):
            found.append(country)
    return found[0] if len(found) == 1 else ""

def employee_range(text):
    value = normalized(text)
    patterns = [
        r"(?:company size|tamano de (?:la )?empresa|employees?|empleados?|team size|plantilla)\s*[:\-]?\s*(\d[\d,\.]*)\s*(?:-|–|a|to)\s*(\d[\d,\.]*)",
        r"(\d[\d,\.]*)\s*(?:-|–|a|to)\s*(\d[\d,\.]*)\s*(?:employees?|empleados?|personas)",
        r"(\d[\d,\.]*)\s*(?:employees?|empleados?)\b",
        r"(?:employees?|empleados?|team size|plantilla)\s*:\s*(\d[\d,\.]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            values = [int(re.sub(r"[,.]", "", v)) for v in match.groups()]
            lo, hi = values[0], values[-1]
            if 0 <= lo <= hi <= 10000000:
                return lo, hi
    return None, None

def infer_signals(text):
    value = normalized(text)
    private_only = bool(re.search(r"\bprivate equity\b", value)) and not bool(re.search(r"\b(?:public equity|listed equity|renta variable|equities|stock)\b", value))
    equity = True if re.search(EQUITY, value) and not private_only else None
    if private_only or re.search(r"(?:exclusively|only|exclusivamente|solo) (?:fixed income|real estate|private debt|renta fija)", value):
        equity = False
    analysis = True if re.search(ANALYSIS, value) else None
    return equity, analysis

def role_points(role):
    value = normalized(role)
    if re.search(r"\b(?:former|ex-|previous|anterior|retired|jubilado)\b", value):
        return 0
    if re.search(NOT_BUYER, value):
        return 0
    if re.search(DECISOR, value) or re.search(LEADER, value):
        return 40
    if re.search(MANAGER, value):
        return 25
    if re.search(ANALYST, value):
        return 10
    return 0

def evidence(field, value, url, quote, observed_at=None):
    return {"field": field, "value": value, "url": url, "quote": str(quote)[:900], "observed_at": observed_at or now()}

SOFT_ISSUES = {"ai_review", "possible_duplicate"}

def resolve_conflicts(contact):
    """Sources that disagree only in compatible ways are not a contradiction: several European offices, or several decision roles."""
    contact = dict(contact)
    issues = list(contact.get("issues", []))
    evidence_list = contact.get("evidence", [])
    countries = [e["value"] for e in evidence_list if e.get("field") == "country" and e.get("value")]
    if "conflict:country" in issues and countries and all(c in EUROPE for c in countries):
        contact["country"] = max(set(countries), key=lambda c: (countries.count(c), c))
        issues.remove("conflict:country")
    roles = [e["value"] for e in evidence_list if e.get("field") == "role" and isinstance(e.get("value"), str) and e["value"].strip()]
    if "conflict:role" in issues and roles and all(role_points(r) > 0 for r in roles):
        contact["role"] = max(roles, key=lambda r: (role_points(r), len(r), roles.count(r)))
        issues.remove("conflict:role")
    contact["issues"] = issues
    return contact

def score_contact(contact):
    contact = resolve_conflicts(contact)
    evidence_list = contact.get("evidence", [])
    issues = list(contact.get("issues", []))
    lo, hi = contact.get("employees_min"), contact.get("employees_max")
    size_known = lo is not None and hi is not None
    size_ok = size_known and lo >= 5 and hi <= 200
    size_out = size_known and (hi < 5 or lo > 200)
    conflict_fields = {i.split(":", 1)[1] for i in issues if i.startswith("conflict:")}
    values = [
        ("role", "Cargo decisor", role_points(contact.get("role", "")), 40),
        ("equity", "Renta variable", 30 if contact.get("equity") is True else 0, 30),
        ("employees", "Gestora de 5 a 200 empleados", 20 if size_ok else 0, 20),
        ("analysis", "Análisis y selección de acciones", 10 if contact.get("analysis") is True else 0, 10),
    ]
    reasons = []
    for field, label, points, maximum in values:
        matched = [e for e in evidence_list if e.get("field") == field]
        if field in conflict_fields or not matched or "association_unverified" in issues or "company" in conflict_fields or (field == "role" and "role_unverified" in issues):
            points = 0
        reasons.append({"field": field, "label": label, "points": points, "maximum": maximum, "evidence": matched})
    score = sum(r["points"] for r in reasons)
    country = contact.get("country", "")
    if size_out or contact.get("equity") is False or (country and country not in EUROPE):
        status = "excluded"
    # Unknown size and review-only notices are shown as pending checks; they do not hide a real decision maker.
    elif contact.get("equity") is True and country in EUROPE and reasons[0]["points"] > 0 and not [i for i in issues if i not in SOFT_ISSUES]:
        status = "qualified"
    else:
        status = "review"
    missing = []
    if not size_known: missing.append("Tamaño sin verificar")
    elif not size_ok and not size_out: missing.append("El rango de empleados cruza el límite objetivo")
    if contact.get("equity") is None: missing.append("Especialización sin verificar")
    if not country: missing.append("País sin verificar")
    if not contact.get("linkedin_url"): missing.append("LinkedIn no localizado")
    if not reasons[0]["points"]: missing.append("Cargo actual sin verificar")
    return {**contact, "score": score, "priority": "high" if score >= 80 else "medium" if score >= 60 else "low",
            "status": status, "reasons": reasons, "missing": missing}

def expand_queries(keywords, country=""):
    geo = country.strip() or "España Europe"
    terms = [t.strip() for t in re.split(r"[,;\n]+", keywords) if t.strip()]
    aliases = ["renta variable", "equity", "equities", "asset management", "gestora", "CIO", "head of equities", "director de inversiones", "stock selection"]
    expanded = list(dict.fromkeys(terms + aliases))
    seed = " ".join(terms)[:160]
    queries = [
        {"phase": "firms", "text": f'{seed} gestora renta variable equipo empleados {geo}'},
        {"phase": "firms", "text": f'{seed} independent equity asset management team employees {geo}'},
        {"phase": "firms", "text": f'{seed} boutique investment management equities {geo}'},
        {"phase": "firms", "text": f'{seed} gestoras fondos acciones equipo inversión {geo}'},
        {"phase": "people", "text": 'site:linkedin.com/in/ "{gestora}" CIO chief investment officer head of equities'},
        {"phase": "people", "text": 'site:linkedin.com/in/ "{gestora}" director inversiones portfolio manager equity'},
        {"phase": "people", "text": 'site:{dominio} "{gestora}" team equipo investment director equity'},
        {"phase": "people", "text": '"{gestora}" company size empleados location equity stock selection'},
    ]
    return {"terms": expanded, "queries": queries, "max_queries": 20, "max_firms": 4}
