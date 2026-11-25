"""Fornecedores de geração estruturada para o Proposer e futuros agentes."""
from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Protocol, TypeVar

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
T = TypeVar("T", bound=BaseModel)
LOGGER = logging.getLogger(__name__)

RATE_LIMIT_HEADER_NAMES = {
    "retry-after", "x-request-id", "request-id",
    "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
    "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens",
    "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset",
}


class LLMError(RuntimeError):
    """Provider failure with optional model outputs, never provider secrets."""

    def __init__(self, message: str, *, failed_outputs: list[str] | None = None,
                 diagnostics: dict | None = None):
        super().__init__(message)
        self.failed_outputs = failed_outputs or []
        self.diagnostics = diagnostics or {}


class RateLimitError(LLMError):
    """Explicit IAedu limit response with safe, credential-free diagnostics."""

    def __init__(self, message: str, *, retry_after: float | None = None,
                 quota_exhausted: bool = False, diagnostics: dict | None = None):
        super().__init__(message, diagnostics=diagnostics)
        self.retry_after = retry_after
        self.quota_exhausted = quota_exhausted


def _safe_rate_headers(headers) -> dict[str, str]:
    return {str(key).lower(): str(value)[:500] for key, value in headers.items()
            if str(key).lower() in RATE_LIMIT_HEADER_NAMES}


def _retry_after_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return max(0.0, (moment - (now or datetime.now(timezone.utc))).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _quota_exhausted(detail: str, headers: dict[str, str]) -> bool:
    text = detail.lower()
    hard_markers = ("insufficient_quota", "quota exhausted", "quota exceeded",
                    "daily quota", "monthly quota", "billing", "out of credits")
    return any(marker in text for marker in hard_markers)


def _limit_kind(detail: str, headers: dict[str, str]) -> str:
    text = detail.lower()
    if "token" in text or headers.get("x-ratelimit-remaining-tokens") == "0":
        return "tokens"
    if ("request" in text or headers.get("x-ratelimit-remaining-requests") == "0"
            or headers.get("ratelimit-remaining") == "0"):
        return "requests"
    if _quota_exhausted(detail, headers):
        return "quota"
    return "unspecified"


def _safe_http_detail(response, secrets: tuple[str, ...]) -> str:
    """Extract a short provider error without leaking configured credentials."""
    try:
        payload = response.json()
    except (ValueError, requests.RequestException):
        payload = None
    if isinstance(payload, dict):
        detail = next((payload.get(key) for key in ("detail", "message", "error")
                       if isinstance(payload.get(key), (str, int, float))), None)
        text = str(detail) if detail is not None else json.dumps(payload, ensure_ascii=False)
    else:
        raw = getattr(response, "text", "")
        text = raw if isinstance(raw, str) else ""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return " ".join(text.split())[:500]


class Provider(Protocol):
    name: str
    model: str

    def generate_structured(self, prompt: str, schema: type[T], *, system: str = "") -> T: ...
    def generation_config(self) -> dict: ...


def _parse_json_object(text: str, schema: type[T]) -> T:
    """Aceita JSON puro ou um objeto JSON rodeado de texto/cerca Markdown."""
    decoder = json.JSONDecoder()
    found_object = False
    first_validation_error: ValidationError | None = None
    for i, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found_object = True
            try:
                return schema.model_validate(value)
            except ValidationError as exc:
                # The model may emit an illustrative object before the actual
                # payload. Continue scanning, but preserve the outermost
                # object's error rather than a later nested object's error.
                if first_validation_error is None:
                    first_validation_error = exc
                continue
    if found_object and first_validation_error is not None:
        raise first_validation_error
    raise ValueError("a resposta não contém um objeto JSON válido")


def prompt_json_schema(schema: type[BaseModel]) -> dict:
    """Drop non-semantic Pydantic metadata from the schema shown to an LLM."""
    def compact(value, *, mapping_container: bool = False):
        if isinstance(value, list):
            return [compact(item) for item in value]
        if not isinstance(value, dict):
            return value
        output = {}
        for key, item in value.items():
            # Do not confuse a real property named `title` with JSON Schema's
            # generated title metadata on the property's schema.
            if not mapping_container and key in {"title", "default"}:
                continue
            output[key] = compact(
                item, mapping_container=key in {"properties", "$defs"})
        return output

    return compact(schema.model_json_schema())


def _json_looks_incomplete(text: str) -> tuple[bool, int, bool]:
    """Detect lexical EOF inside a JSON object without retaining its content."""
    start = text.find("{")
    if start < 0:
        return False, 0, False
    stack: list[str] = []
    in_string = False
    escaped = False
    pairs = {"}": "{", "]": "["}
    for char in text[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack or stack[-1] != pairs[char]:
                return False, len(stack), in_string
            stack.pop()
    return bool(stack or in_string), len(stack), in_string


def _structured_output_diagnostic(text: str, schema: type[T]) -> dict:
    """Return a concise, content-free diagnosis for a structured response."""
    base = {"output_chars": len(text)}
    if "{" not in text:
        return base | {"category": "no_json_object",
                       "reason": "response contains no JSON object"}
    incomplete, open_delimiters, unterminated_string = _json_looks_incomplete(text)
    if incomplete:
        return base | {
            "category": "incomplete_json",
            "reason": "response ended before the JSON object was closed",
            "open_delimiters": open_delimiters,
            "unterminated_string": unterminated_string,
        }
    try:
        _parse_json_object(text, schema)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        fields = [".".join(str(part) for part in item.get("loc", ())) or "<root>"
                  for item in errors[:5]]
        return base | {"category": "schema_validation",
                       "reason": "complete JSON object does not match the schema",
                       "error_count": len(errors), "fields": fields}
    except ValueError:
        return base | {"category": "invalid_json",
                       "reason": "JSON syntax is invalid or no complete object was found"}
    return base | {"category": "valid", "reason": "valid structured response"}


def _retry_feedback(diagnostic: dict) -> str:
    category = diagnostic["category"]
    if category in {"incomplete_json", "output_truncated"}:
        return ("A resposta terminou antes de fechar o JSON. Recomeça do início e devolve um "
                "objeto completo e mais conciso; mantém todos os campos obrigatórios, sem "
                "repetir detalhes do calendário na justificação.")
    if category == "stream_protocol_error":
        return ("A resposta anterior terminou com um erro técnico de streaming. Recomeça do "
                "início e devolve apenas o objeto JSON completo.")
    if category == "schema_validation":
        fields = ", ".join(diagnostic.get("fields", [])) or "campos desconhecidos"
        return (f"O JSON estava completo, mas falhou o esquema nos campos: {fields}. "
                "Corrige esses campos e devolve apenas o objeto completo.")
    if category == "no_json_object":
        return "A resposta não continha um objeto JSON. Devolve apenas o objeto JSON completo."
    return "A sintaxe JSON estava inválida. Devolve apenas um objeto JSON completo e válido."


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
                 max_retries: int | None = None, timeout: tuple[int, int] = (10, 180),
                 rate_limit_max_retries: int | None = None,
                 rate_limit_base_delay: float | None = None,
                 rate_limit_max_delay: float | None = None,
                 rate_limit_jitter: float | None = None,
                 sleep_fn: Callable[[float], None] = time.sleep,
                 random_fn: Callable[[], float] = random.random):
        self.model = model or os.getenv("IAEDU_MODEL_LABEL", "GPT-5.5")
        self.api_key = api_key or os.getenv("IAEDU_API_KEY", "")
        self.endpoint = endpoint or os.getenv("IAEDU_API_ENDPOINT", "")
        self.channel_id = channel_id or os.getenv("IAEDU_CHANNEL_ID", "")
        self.max_retries = (max_retries if max_retries is not None
                            else int(os.getenv("IAEDU_STRUCTURED_MAX_RETRIES", "2")))
        self.timeout = timeout
        self.rate_limit_max_retries = (rate_limit_max_retries if rate_limit_max_retries is not None
            else int(os.getenv("IAEDU_RATE_LIMIT_MAX_RETRIES", "3")))
        self.rate_limit_base_delay = (rate_limit_base_delay if rate_limit_base_delay is not None
            else float(os.getenv("IAEDU_RATE_LIMIT_BASE_DELAY", "15")))
        self.rate_limit_max_delay = (rate_limit_max_delay if rate_limit_max_delay is not None
            else float(os.getenv("IAEDU_RATE_LIMIT_MAX_DELAY", "300")))
        self.rate_limit_jitter = (rate_limit_jitter if rate_limit_jitter is not None
            else float(os.getenv("IAEDU_RATE_LIMIT_JITTER", "0.2")))
        if self.max_retries < 1:
            raise ValueError("IAEDU_STRUCTURED_MAX_RETRIES must be at least 1")
        if self.rate_limit_max_retries < 0 or self.rate_limit_base_delay < 0 or self.rate_limit_max_delay < 0:
            raise ValueError("IAedu retry settings must be non-negative")
        if not 0 <= self.rate_limit_jitter <= 1:
            raise ValueError("IAEDU_RATE_LIMIT_JITTER must be between 0 and 1")
        self._sleep, self._random = sleep_fn, random_fn
        self.last_failed_outputs: list[str] = []
        self.last_structured_output_diagnostics: list[dict] = []
        self.last_rate_limit_attempts: list[dict] = []
        self.last_stream_diagnostics: dict = {}

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
                "thread_policy": "new_uuid_per_request",
                "rate_limit_max_retries": self.rate_limit_max_retries,
                "rate_limit_base_delay_seconds": self.rate_limit_base_delay,
                "rate_limit_max_delay_seconds": self.rate_limit_max_delay,
                "rate_limit_jitter": self.rate_limit_jitter}

    def _rate_limit_error(self, detail: str, response, *, source: str) -> RateLimitError:
        headers = _safe_rate_headers(getattr(response, "headers", {}) or {})
        retry_after = _retry_after_seconds(headers.get("retry-after"))
        exhausted = _quota_exhausted(detail, headers)
        diagnostic = {"source": source, "http_status": getattr(response, "status_code", None),
                      "detail": detail[:500], "headers": headers,
                      "retry_after_seconds": retry_after,
                      "limit_kind": _limit_kind(detail, headers),
                      "quota_exhausted": exhausted}
        return RateLimitError(f"IAedu rate limit: {detail[:300]}", retry_after=retry_after,
                              quota_exhausted=exhausted, diagnostics=diagnostic)

    def _wait_for_rate_limit(self, error: RateLimitError, retry_index: int) -> float:
        if error.retry_after is not None:
            delay = error.retry_after
        else:
            base = min(self.rate_limit_max_delay,
                       self.rate_limit_base_delay * (2 ** retry_index))
            factor = 1 + self.rate_limit_jitter * (2 * self._random() - 1)
            delay = max(0.0, base * factor)
        return delay

    def generate_text(self, message: str, *, thread_id: str | None = None) -> str:
        """Protocolo multipart e linhas JSON do exemplo oficial IAedu."""
        self._check_config()
        self.last_rate_limit_attempts = []
        self.last_stream_diagnostics = {}
        fixed_thread = thread_id
        for retry_index in range(self.rate_limit_max_retries + 1):
            files = {"channel_id": (None, self.channel_id),
                     "thread_id": (None, fixed_thread or str(uuid.uuid4())),
                     "user_info": (None, json.dumps({})),
                     "message": (None, message)}
            try:
                response = requests.post(self.endpoint, headers={"x-api-key": self.api_key},
                                         files=files, stream=True, timeout=self.timeout)
                try:
                    if response.status_code == 429:
                        excerpt = response.text[:500] if isinstance(response.text, str) else "HTTP 429"
                        raise self._rate_limit_error(excerpt or "HTTP 429", response, source="http")
                    try:
                        response.raise_for_status()
                    except requests.HTTPError:
                        detail = _safe_http_detail(
                            response, (self.api_key, self.channel_id, self.endpoint))
                        suffix = f": {detail}" if detail else ""
                        raise LLMError(
                            f"IAedu devolveu HTTP {response.status_code}{suffix}",
                            diagnostics={"http_status": response.status_code,
                                         "detail": detail or None,
                                         "headers": _safe_rate_headers(response.headers)},
                        ) from None
                    parts: list[str] = []
                    terminal_events: list[dict] = []
                    event_count = 0
                    for line in response.iter_lines():
                        if not line:
                            continue
                        event_count += 1
                        try:
                            event = json.loads(line.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            diagnostics = {
                                "classification": "stream_protocol_error",
                                "event_index": event_count,
                                "line_bytes": len(line),
                                "tokens_collected": len(parts),
                            }
                            raise LLMError("IAedu devolveu uma linha de streaming inválida",
                                           failed_outputs=["".join(parts)] if parts else [],
                                           diagnostics=diagnostics) from None
                        if not isinstance(event, dict):
                            continue
                        if event.get("type") == "error":
                            detail = next((event.get(key) for key in ("message", "content", "error", "code")
                                           if isinstance(event.get(key), (str, int))), None)
                            detail = str(detail) if detail is not None else "stream error"
                            if "429" in detail or "rate limit" in detail.lower() or "quota" in detail.lower():
                                raise self._rate_limit_error(detail, response, source="stream_event")
                            raise LLMError("IAedu devolveu um evento de erro no streaming: " + detail[:300])
                        if event.get("type") == "token" and isinstance(event.get("content"), str):
                            parts.append(event["content"])
                        elif event.get("type") != "error":
                            safe = {"type": event.get("type")}
                            for key in ("finish_reason", "stop_reason", "status"):
                                if isinstance(event.get(key), (str, int, float, bool)):
                                    safe[key] = event[key]
                            usage = event.get("usage")
                            if isinstance(usage, dict):
                                safe["usage"] = {key: value for key, value in usage.items()
                                                 if isinstance(value, (int, float))}
                            terminal_events.append(safe)
                    if not parts:
                        raise LLMError("IAedu não devolveu tokens de texto")
                    output = "".join(parts)
                    finish_reasons = [str(event.get("finish_reason") or event.get("stop_reason") or "").lower()
                                      for event in terminal_events]
                    self.last_stream_diagnostics = {
                        "classification": "complete_stream",
                        "event_count": event_count,
                        "token_events": len(parts),
                        "output_chars": len(output),
                        "terminal_events": terminal_events,
                    }
                    if any(reason in {"length", "max_tokens", "max_output_tokens"}
                           for reason in finish_reasons):
                        diagnostics = self.last_stream_diagnostics | {
                            "classification": "output_truncated"}
                        raise LLMError("IAedu terminou a resposta por limite de output",
                                       failed_outputs=[output], diagnostics=diagnostics)
                    return output
                finally:
                    response.close()
            except RateLimitError as exc:
                attempt = dict(exc.diagnostics) | {"attempt": retry_index + 1}
                self.last_rate_limit_attempts.append(attempt)
                exhausted = exc.quota_exhausted
                no_more_retries = retry_index >= self.rate_limit_max_retries
                delay = self._wait_for_rate_limit(exc, retry_index)
                long_reset = delay > self.rate_limit_max_delay
                if exhausted or no_more_retries or long_reset:
                    reason = ("quota_exhausted" if exhausted else "long_retry_after"
                              if long_reset else "retry_exhausted")
                    diagnostics = {"classification": reason,
                                   "attempts": self.last_rate_limit_attempts}
                    raise RateLimitError(str(exc), retry_after=exc.retry_after,
                                         quota_exhausted=exhausted,
                                         diagnostics=diagnostics) from None
                attempt["wait_seconds"] = round(delay, 3)
                LOGGER.warning("IAedu 429 attempt %s/%s; waiting %.3fs; kind=%s",
                               retry_index + 1, self.rate_limit_max_retries + 1, delay,
                               attempt["limit_kind"])
                self._sleep(delay)
            except requests.RequestException:
                raise LLMError("Falha de comunicação com IAedu") from None
        raise AssertionError("unreachable IAedu retry state")

    def generate_structured(self, prompt: str, schema: type[T], *, system: str = "") -> T:
        instruction = (f"{system}\n\nDevolve exclusivamente um objeto JSON conforme este JSON Schema:\n"
                       f"{json.dumps(prompt_json_schema(schema), ensure_ascii=False, separators=(',', ':'))}"
                       f"\n\n{prompt}")
        failed_outputs: list[str] = []
        diagnostics: list[dict] = []
        retry_feedback = ""
        self.last_failed_outputs = []
        self.last_structured_output_diagnostics = []
        for attempt in range(self.max_retries):
            suffix = "" if attempt == 0 else f"\n\n{retry_feedback}"
            try:
                output = self.generate_text(instruction + suffix)
            except LLMError as exc:
                category = exc.diagnostics.get("classification")
                if category not in {"output_truncated", "stream_protocol_error"}:
                    raise
                failed_outputs.extend(exc.failed_outputs)
                diagnostic = dict(exc.diagnostics) | {"category": category, "attempt": attempt + 1}
                diagnostics.append(diagnostic)
                self.last_failed_outputs = list(failed_outputs)
                self.last_structured_output_diagnostics = list(diagnostics)
                retry_feedback = _retry_feedback(diagnostic)
                LOGGER.warning("IAedu structured stream attempt %s/%s failed: %s",
                               attempt + 1, self.max_retries, category)
                continue
            try:
                return _parse_json_object(output, schema)
            except (ValidationError, ValueError):
                failed_outputs.append(output)
                diagnostic = _structured_output_diagnostic(output, schema) | {"attempt": attempt + 1}
                diagnostics.append(diagnostic)
                self.last_failed_outputs = list(failed_outputs)
                self.last_structured_output_diagnostics = list(diagnostics)
                retry_feedback = _retry_feedback(diagnostic)
                LOGGER.warning("IAedu structured response attempt %s/%s failed: %s (%s chars)",
                               attempt + 1, self.max_retries, diagnostic["category"],
                               diagnostic["output_chars"])
        last = diagnostics[-1]
        raise LLMError(
            f"IAedu: {self.max_retries} respostas estruturadas inválidas; "
            f"última causa: {last['category']}",
            failed_outputs=failed_outputs,
            diagnostics={"classification": "structured_output_exhausted",
                         "attempts": diagnostics},
        )


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
