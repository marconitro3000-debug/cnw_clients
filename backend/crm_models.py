from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, SecretStr, field_validator
from .models import ContactInput

Stage = Literal['pending','contacted','no_response','replied','interested','demo','customer','discarded']
class InteractionInput(BaseModel):
    author: str = Field(min_length=1,max_length=100)
    channel: Literal['call','linkedin','email','note'] = 'note'
    result: Stage | None = None
    clear_follow_up: bool = False
    comment: str = Field(default='',max_length=10000)
    occurred_at: str | None = None
    follow_up: str | None = None
    script_uuid: str | None = None
    script_version: int | None = Field(default=None,ge=1)
    @field_validator('occurred_at','follow_up')
    @classmethod
    def valid_date(cls,v):
        if not v: return None
        date=datetime.fromisoformat(v.replace('Z','+00:00'))
        return date.replace(tzinfo=timezone.utc).isoformat() if date.tzinfo is None else date.astimezone(timezone.utc).isoformat()
    @field_validator('author')
    @classmethod
    def nonempty(cls,v):
        if not v.strip(): raise ValueError('Indica quién registra la interacción.')
        return v.strip()

class ScriptInput(BaseModel):
    title: str = Field(min_length=2,max_length=150)
    channel: Literal['call','linkedin','email']
    text: str = Field(min_length=1,max_length=20000)
    english_text: str = Field(default='',max_length=20000)
    archived: bool = False

class ApolloSettingsInput(BaseModel):
    api_key: SecretStr | None = None
    free_budget: int = Field(default=0,ge=0,le=100000)
    free_account: bool = False

class ApolloSearchInput(BaseModel):
    source: Literal['people','saved_contacts'] = 'people'
    continuous: bool = False
    keywords: str = Field(default='equity asset management',max_length=6000)
    @field_validator('keywords',mode='before')
    @classmethod
    def multiple_keywords(cls,value):
        import re
        if isinstance(value,list):
            if not all(isinstance(term,str) for term in value): raise ValueError('Las palabras clave deben ser textos.')
            value='\n'.join(value)
        if not isinstance(value,str): raise ValueError('Introduce palabras clave como texto o lista.')
        terms=[];seen=set()
        for term in re.split(r'[\n,;]+',value):
            term=' '.join(term.split())
            if not term or term.casefold() in seen: continue
            if len(term)>300: raise ValueError('Cada palabra o frase admite hasta 300 caracteres.')
            seen.add(term.casefold());terms.append(term)
        if len(terms)>20: raise ValueError('Introduce un máximo de 20 palabras o frases clave.')
        return '\n'.join(terms)
    @property
    def keyword_terms(self): return self.keywords.split('\n') if self.keywords else ['']
    countries: list[str] = Field(default_factory=lambda:['Spain'],min_length=1,max_length=50)
    titles: list[str] = Field(default_factory=lambda:['Chief Investment Officer','Head of Equities','Investment Director'],min_length=1,max_length=25)
    domains: list[str] = Field(default_factory=list,max_length=1000)
    employees_min: int = Field(default=5,ge=1,le=200)
    employees_max: int = Field(default=200,ge=1,le=200)
    page: int = Field(default=1,ge=1,le=500)
    @field_validator('domains')
    @classmethod
    def valid_domains(cls,values):
        import re
        if any(not re.fullmatch(r'[A-Za-z0-9.-]+\.[A-Za-z]{2,}',v) for v in values): raise ValueError('Introduce dominios sin https ni rutas.')
        return values
    def model_post_init(self,context):
        if self.employees_min>self.employees_max: raise ValueError('Rango de tamaño incorrecto.')

class ApolloEnrichInput(BaseModel):
    contact_ids: list[int] = Field(min_length=1,max_length=50)
    phone: bool = False
    force_contact_id: int | None = None

class CandidateAcceptInput(BaseModel):
    enrich: bool = False
    run_id: int
    candidate_ids: list[str] = Field(min_length=1,max_length=50)

class CSVPreviewInput(BaseModel):
    text: str = Field(min_length=1,max_length=3000000)
class CSVImportInput(CSVPreviewInput):
    mapping: dict[str,str]

class CRMContactInput(BaseModel):
    owner: str = Field(default='',max_length=100)
    email: str | None = Field(default=None,max_length=254)
    phone: str | None = Field(default=None,max_length=60)
    @field_validator('email')
    @classmethod
    def valid_email(cls,v):
        import re
        if v and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v): raise ValueError('Correo inválido.')
        return v

Answer = Literal['yes','no'] | None
class QualificationInput(BaseModel):
    change: Answer = None
    timing: Answer = None
    decision: Answer = None

class SegmentInput(BaseModel):
    segment: Literal['quant','hedge_fund','boutique_equity','thematic','wealth','multi_asset','private_markets','unclassified'] | None = None

class ResolveInput(BaseModel):
    choice: Literal['local','incoming']
class OllamaInput(BaseModel):
    enabled: bool = False
    model: str = Field(default='qwen3:4b-instruct-2507-q4_K_M',min_length=1,max_length=100)
    @field_validator('model')
    @classmethod
    def local_model(cls,value):
        if '/' in value or 'cloud' in value.lower(): raise ValueError('Selecciona un modelo local instalado.')
        return value
class NextBatchInput(BaseModel):
    use_ollama: bool = False

class PublicSearchInput(BaseModel):
    contact_ids: list[int] = Field(default_factory=list,max_length=50)
    continuous: bool = True

class SignalSearchInput(BaseModel):
    firm_ids: list[int] = Field(default_factory=list,max_length=1000)
    days: int = Field(default=90,ge=7,le=365)
    continuous: bool = True

class SignalReviewInput(BaseModel):
    decision: Literal['confirmed','rejected','pending']
