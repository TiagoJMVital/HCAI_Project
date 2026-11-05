"""Cliente mínimo do Ollama com saída estruturada validada por Pydantic."""
from __future__ import annotations

import json
import os
from typing import Type, TypeVar

import requests
from pydantic import BaseModel, ValidationError

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def generate_structured(
    prompt: str,
    schema: Type[T],
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    max_retries: int = 3,
    timeout: int = 300,
) -> T:
    """Pede ao modelo uma resposta que obedece ao JSON Schema de `schema`.

    O Ollama aceita um JSON Schema no campo `format` (saída estruturada).
    Se a validação Pydantic falhar, repete com o erro anexado ao prompt.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system or "",
        "format": schema.model_json_schema(),
        "stream": False,
        "options": {"temperature": temperature},
    }
    last_error = ""
    for attempt in range(1, max_retries + 1):
        if last_error:
            payload["prompt"] = (
                f"{prompt}\n\nA tua resposta anterior era inválida: {last_error}\n"
                "Corrige e devolve apenas JSON válido."
            )
        try:
            r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=timeout)
            r.raise_for_status()
            return schema.model_validate_json(r.json()["response"])
        except (ValidationError, json.JSONDecodeError) as e:
            last_error = str(e)[:500]
        except requests.RequestException as e:
            raise LLMError(f"Falha a contactar o Ollama em {OLLAMA_URL}: {e}") from e
    raise LLMError(f"Sem resposta válida após {max_retries} tentativas: {last_error}")
