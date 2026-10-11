import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import UnicodeDammit
from dotenv import load_dotenv, set_key
from .domain import is_linkedin, now, safe_url

ROOT = Path(__file__).resolve().parent.parent

@dataclass
class Settings:
    api_key: str = ""
    monthly_limit: int = 1000
    database_path: str = str(ROOT / "data" / "scout.sqlite")
    env_path: str = str(ROOT / ".env")

    shared_path: str | None = None
    apollo_key: str = ""

    @classmethod
    def from_env(cls):
        env_path = os.getenv("SCOUT_ENV_PATH", str(ROOT / ".env"))
        load_dotenv(env_path)
        limit = max(0, min(1000, int(os.getenv("MONTHLY_SEARCH_LIMIT", "1000"))))
        return cls(os.getenv("TAVILY_API_KEY", "").strip(), limit, os.getenv("SCOUT_DATABASE_PATH", str(ROOT / "data" / "scout.sqlite")), env_path, os.getenv("SCOUT_SHARED_PATH"), os.getenv("APOLLO_API_KEY", "").strip())

    def save_api_key(self, key):
        # set_key writes through a temporary file and preserves other settings.
        Path(self.env_path).parent.mkdir(parents=True, exist_ok=True)
        set_key(self.env_path, "TAVILY_API_KEY", key, quote_mode="always")
        self.api_key = key

    @property
    def account(self):
        return hashlib.sha256(self.api_key.encode()).hexdigest()[:20] if self.api_key else ""

class ProviderError(Exception):
    pass

class QuotaError(ProviderError):
    pass

class Tavily:
    def __init__(self, settings, db, transport=None):
        self.settings, self.db, self.transport = settings, db, transport

    async def search_signals(self, query, run_id, days=90):
        today=datetime.now(timezone.utc).date()
        options={"include_published_date":True,"start_date":(today-timedelta(days=days)).isoformat(),"end_date":today.isoformat()}
        scoped=re.search(r'(?:^|\s)site:([a-zA-Z0-9.-]+)',query)
        if scoped:options['include_domains']=[scoped.group(1)]
        return await self.search(query,run_id,options)

    async def search(self, query, run_id, options=None):
        key = "search:basic:v1:" + self.settings.account + ":" + query.strip()
        if options: key += ":" + hashlib.sha256(json.dumps(options,sort_keys=True).encode()).hexdigest()
        cached = self.db.cache_get(key)
        if cached is not None:
            return cached, True
        if not self.settings.api_key:
            raise ProviderError("Falta TAVILY_API_KEY en el archivo .env.")
        if not self.db.reserve_credit(self.settings.account, run_id, self.settings.monthly_limit):
            raise QuotaError("Se ha alcanzado el límite mensual local de búsquedas. Los resultados se conservan.")
        try:
            async with httpx.AsyncClient(timeout=25, transport=self.transport, trust_env=False) as client:
                response = await client.post("https://api.tavily.com/search",
                    headers={"Authorization": "Bearer " + self.settings.api_key},
                    json={"query": query, "search_depth": "basic", "max_results": 5,
                          "topic": "general", "auto_parameters": False, "include_answer": False,
                          "include_raw_content": False, "include_images": False, "include_usage": True, **(options or {})})
        except httpx.HTTPError:
            raise ProviderError("No se pudo conectar con Tavily. Comprueba tu conexión y vuelve a intentarlo.") from None
        if response.status_code in (402, 432, 433):
            raise QuotaError("Tavily ha agotado o limitado la cuota. Se conservan los resultados parciales.")
        if response.status_code == 429:
            raise ProviderError("Tavily ha limitado la frecuencia de peticiones. Espera antes de iniciar otra búsqueda.")
        if response.status_code in (401, 403):
            raise ProviderError("Tavily no ha aceptado la clave. Corrígela en Configuración y vuelve a buscar.")
        if not response.is_success:
            raise ProviderError(f"Tavily ha devuelto un error HTTP {response.status_code}.")
        try:
            payload = response.json()
            if not isinstance(payload.get("results"), list):
                raise ValueError()
        except (ValueError, AttributeError):
            raise ProviderError("Tavily ha devuelto una respuesta no válida.") from None
        stamp = now()
        results = [{**r, "observed_at": stamp} for r in payload["results"] if isinstance(r, dict)]
        self.db.cache_put(key, results)
        return results, False

class WebFetcher:
    """Small corporate-page reader. Blocks LinkedIn, private hosts and disallowed robots."""
    def __init__(self, db):
        self.db = db
        self.robots = {}
        self.pages = 0
        self.max_pages = 16

    async def validate(self, url):
        if not safe_url(url) or is_linkedin(url):
            raise ProviderError("Fuente omitida: URL no pública o dominio LinkedIn.")
        hostname = urlparse(url).hostname
        try:
            addresses = await asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise ProviderError("No se pudo resolver el dominio de una fuente.") from None
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ProviderError("Fuente omitida: el dominio no resuelve a direcciones públicas.")

    async def request(self, url, limit):
        async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False,
            headers={"User-Agent": "EquityScout/1.0 (public corporate research)"}) as client:
            for _ in range(4):
                await self.validate(url)
                async with client.stream("GET", url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location: raise ProviderError("Redirección sin destino.")
                        url = urljoin(url, location)
                        continue
                    if response.status_code in (401, 403):
                        raise ProviderError("La fuente requiere acceso o no permite lectura.")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > limit:
                            raise ProviderError("Fuente omitida: página demasiado grande.")
                    return response.status_code, UnicodeDammit(bytes(data), known_definite_encodings=[response.encoding] if "charset=" in response.headers.get("content-type","").lower() else [], is_html=True).unicode_markup or bytes(data).decode("utf-8",errors="replace"), url, response.headers.get("content-type", "")
            raise ProviderError("Demasiadas redirecciones en una fuente.")

    async def page(self, url):
        await self.validate(url)
        cached = self.db.cache_get("page:v2:" + url)
        if cached: return cached
        if self.pages >= self.max_pages:
            raise ProviderError("Alcanzado el límite de páginas corporativas de esta búsqueda.")
        origin = urlparse(url).scheme + "://" + urlparse(url).netloc
        if origin not in self.robots:
            status, text, _, _ = await self.request(origin + "/robots.txt", 200000)
            parser = RobotFileParser()
            if status == 404: parser.parse([])
            elif status == 200: parser.parse(text.splitlines())
            else:
                raise ProviderError("No se pudo comprobar robots.txt; fuente omitida.")
            self.robots[origin] = parser
        if not self.robots[origin].can_fetch("EquityScout", url):
            raise ProviderError("La fuente no permite leer esta página según robots.txt.")
        self.pages += 1
        status, html, final_url, content_type = await self.request(url, 2000000)
        if status != 200 or "html" not in content_type:
            raise ProviderError("Fuente omitida: no es una página HTML accesible.")
        # A redirect to another origin must also have a permissive robots policy.
        final_origin = urlparse(final_url).scheme + "://" + urlparse(final_url).netloc
        if final_origin != origin:
            initial_host=(urlparse(url).hostname or '').lower().removeprefix('www.')
            final_host=(urlparse(final_url).hostname or '').lower().removeprefix('www.')
            if final_host!=initial_host:
                raise ProviderError("Fuente omitida: redirección a otro dominio; vuelve a buscar su URL final.")
            if final_origin not in self.robots:
                robot_status,robot_text,_,_=await self.request(final_origin+"/robots.txt",200000)
                parser=RobotFileParser()
                if robot_status==404: parser.parse([])
                elif robot_status==200: parser.parse(robot_text.splitlines())
                else: raise ProviderError("No se pudo comprobar robots.txt; fuente omitida.")
                self.robots[final_origin]=parser
            if not self.robots[final_origin].can_fetch("EquityScout",final_url):
                raise ProviderError("La fuente no permite leer esta página según robots.txt.")
        value = {"html": html, "url": final_url, "observed_at": now()}
        self.db.cache_put("page:v2:" + url, value)
        return value
