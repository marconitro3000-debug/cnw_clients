from typing import Literal
from pydantic import BaseModel, Field, SecretStr, field_validator
from .domain import linkedin_url, safe_url

class ExpandInput(BaseModel):
    keywords: str = Field(default="renta variable", min_length=1, max_length=300)
    country: str = Field(default="", max_length=100)

class Query(BaseModel):
    text: str = Field(min_length=3, max_length=700)
    phase: Literal["firms", "people"]

class SearchInput(BaseModel):
    continuous: bool = False
    use_ollama: bool = False
    parent_run_id: int | None = None
    keywords: str = Field(min_length=1, max_length=300)
    queries: list[Query] = Field(min_length=1, max_length=20)

class ContactInput(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    role: str = Field(default="", max_length=200)
    company: str = Field(min_length=2, max_length=200)
    country: str = Field(default="", max_length=80)
    employees_min: int | None = Field(default=None, ge=0, le=10000000)
    employees_max: int | None = Field(default=None, ge=0, le=10000000)
    equity: bool | None = None
    analysis: bool | None = None
    linkedin_url: str | None = None
    photo_url: str | None = None
    note: str = Field(default="", max_length=1500)

    @field_validator("linkedin_url")
    @classmethod
    def valid_linkedin(cls, value):
        if not value:
            return None
        normalized = linkedin_url(value)
        if not normalized:
            raise ValueError("Introduce una URL de perfil linkedin.com/in/ válida.")
        return normalized

    @field_validator("photo_url")
    @classmethod
    def valid_photo(cls, value):
        if not value:
            return None
        if not safe_url(value):
            raise ValueError("La imagen debe tener una URL pública HTTP o HTTPS.")
        return value

    def model_post_init(self, context):
        if self.employees_min is not None and self.employees_max is not None:
            if self.employees_min > self.employees_max:
                raise ValueError("El mínimo de empleados no puede superar el máximo.")

class TavilyKeyInput(BaseModel):
    api_key: SecretStr
