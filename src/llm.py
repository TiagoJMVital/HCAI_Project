"""Fornecedores de geração estruturada para o Proposer e futuros agentes."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Protocol, TypeVar

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Erro sem dados da resposta nem valores de configuração sensíveis."""


class Provider(Protocol):
    name: str
    model: str

    def generate_structured(self, prompt: str, schema: type[T], *, system: str = "") -> T: ...
    def generation_config(self) -> dict: ...


def _parse_json_object(text: str, schema: type[T]) -> T:
    """Aceita JSON puro ou um objeto JSON rodeado de texto/cerca Markdown."""
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return schema.model_validate(value)
    raise ValueError("a resposta não contém um objeto JSON válido")


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str | None = None, *, url: str | None = None,
                 temperature: float = 0.2, max_retries: int = 3, timeout: int = 300):
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self.url = (url or os.getenv("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.temperature, self.max_retries, self.timeout = temperature, max_retries, timeout

    def generation_config(self) -> dict:
        return {"temperature": self.temperature, "max_retries": self.max_retries,
                "timeout_seconds": self.timeout, "structured_output": "ollama_json_schema"}

    def generate_structured(self, prompt: str, schema: type[T], *, system: str = "") -> T:
        last_error = "resposta inválida"
        for attempt in range(self.max_retries):
            request_prompt = prompt if attempt == 0 else (
                f"{prompt}\n\nA resposta anterior não respeitou o esquema ({last_error}). "
                "Devolve apenas um objeto JSON válido."
            )
            try:
                response = requests.post(
                    f"{self.url}/api/generate",
                    json={"model": self.model, "prompt": request_prompt, "system": system,
                          "format": schema.model_json_schema(), "stream": False,
                          "options": {"temperature": self.temperature}},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return schema.model_validate_json(response.json()["response"])
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "desconhecido"
                raise LLMError(f"Ollama devolveu HTTP {status}") from None
            except requests.RequestException:
                raise LLMError("Falha de comunicação com Ollama") from None
            except (ValidationError, ValueError, KeyError, TypeError):
                last_error = "JSON ou campos inválidos"
        raise LLMError(f"Ollama: {self.max_retries} respostas inválidas")


class IAeduProvider:
    name = "iaedu"

    def __init__(self, model: str | None = None, *, api_key: str | None = None,
                 endpoint: str | None = None, channel_id: str | None = None,
                 max_retries: int = 2, timeout: tuple[int, int] = (10, 180)):
        self.model = model or os.getenv("IAEDU_MODEL_LABEL", "GPT-5.5")
        self.api_key = api_key or os.getenv("IAEDU_API_KEY", "")
        self.endpoint = endpoint or os.getenv("IAEDU_API_ENDPOINT", "")
        self.channel_id = channel_id or os.getenv("IAEDU_CHANNEL_ID", "")
        self.max_retries, self.timeout = max_retries, timeout

    def _check_config(self) -> None:
        missing = [name for name, value in (
            ("IAEDU_API_KEY", self.api_key), ("IAEDU_API_ENDPOINT", self.endpoint),
            ("IAEDU_CHANNEL_ID", self.channel_id)) if not value]
        if missing:
            raise LLMError("Configuração IAedu incompleta: " + ", ".join(missing))
        if not self.endpoint.startswith("https://"):
            raise LLMError("IAEDU_API_ENDPOINT deve usar HTTPS")

    def generation_config(self) -> dict:
        return {"max_retries": self.max_retries, "timeout_seconds": list(self.timeout),
                "structured_output": "prompt_and_local_validation",
                "thread_policy": "new_uuid_per_request"}

    def generate_text(self, message: str, *, thread_id: str | None = None) -> str:
        """Protocolo multipart e linhas JSON do exemplo oficial IAedu."""
        self._check_config()
        files = {"channel_id": (None, self.channel_id),
                 "thread_id": (None, thread_id or str(uuid.uuid4())),
                 "user_info": (None, json.dumps({})),
                 "message": (None, message)}
        try:
            response = requests.post(self.endpoint, headers={"x-api-key": self.api_key},
                                     files=files, stream=True, timeout=self.timeout)
            try:
                response.raise_for_status()
                parts: list[str] = []
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") == "error":
                        raise LLMError("IAedu devolveu um evento de erro no streaming")
                    if event.get("type") == "token" and isinstance(event.get("content"), str):
                        parts.append(event["content"])
                if not parts:
                    raise LLMError("IAedu não devolveu tokens de texto")
                return "".join(parts)
            finally:
                response.close()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "desconhecido"
            raise LLMError(f"IAedu devolveu HTTP {status}") from None
        except requests.RequestException:
            raise LLMError("Falha de comunicação com IAedu") from None

    def generate_structured(self, prompt: str, schema: type[T], *, system: str = "") -> T:
        instruction = (f"{system}\n\nDevolve exclusivamente um objeto JSON conforme este JSON Schema:\n"
                       f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}\n\n{prompt}")
        for attempt in range(self.max_retries):
            suffix = "" if attempt == 0 else (
                "\n\nA resposta anterior não foi JSON válido conforme o esquema. "
                "Corrige-a e devolve só o objeto JSON completo."
            )
            try:
                return _parse_json_object(self.generate_text(instruction + suffix), schema)
            except (ValidationError, ValueError):
                continue
        raise LLMError(f"IAedu: {self.max_retries} respostas sem JSON válido conforme o esquema")


def get_provider(*, role: str = "PROPOSER", provider: str | None = None,
                 model: str | None = None) -> Provider:
    """Configuração por agente; o Critic futuro pode escolher outro fornecedor."""
    selected = (provider or os.getenv(f"{role}_LLM_PROVIDER") or
                os.getenv("LLM_PROVIDER", "iaedu")).lower()
    if selected == "iaedu":
        return IAeduProvider(model=model or os.getenv(f"{role}_IAEDU_MODEL_LABEL"))
    if selected == "ollama":
        return OllamaProvider(model=model or os.getenv(f"{role}_OLLAMA_MODEL"))
    raise LLMError(f"LLM_PROVIDER desconhecido: {selected}")


def generate_structured(prompt: str, schema: type[T], *, system: str = "",
                        model: str | None = None, role: str = "PROPOSER") -> T:
    return get_provider(role=role, model=model).generate_structured(prompt, schema, system=system)
