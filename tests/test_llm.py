"""Contrato HTTP dos fornecedores sem chamadas externas nem consumo de tokens."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from llm import (IAeduProvider, LLMError, OllamaProvider, _parse_json_object,
                 get_provider, prompt_json_schema)  # noqa: E402
from models import Change, ProposerWireProposal  # noqa: E402


class Answer(BaseModel):
    ok: bool


def stream(*contents):
    response = Mock()
    response.status_code = 200
    response.headers = {}
    response.text = ""
    response.iter_lines.return_value = [json.dumps({"type": "token", "content": part}).encode()
                                        for part in contents]
    response.raise_for_status.return_value = None
    return response


def rate_response(*, status=429, detail="Rate limit reached", headers=None, stream_event=False):
    response = Mock()
    response.status_code = 200 if stream_event else status
    response.headers = headers or {}
    response.text = detail
    response.raise_for_status.return_value = None
    response.iter_lines.return_value = ([json.dumps({"type": "error", "content": detail}).encode()]
                                        if stream_event else [])
    return response


def test_iaedu_multipart_stream_and_fresh_threads(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return stream('```json\n{"ok":', ' true}\n```')

    monkeypatch.setattr(requests, "post", post)
    client = IAeduProvider(api_key="test-key", endpoint="https://example.invalid/api",
                          channel_id="test-channel")
    assert client.generate_structured("pedido", Answer, system="instrução").ok
    assert client.generate_structured("pedido", Answer).ok
    assert len(calls) == 2
    assert calls[0][1]["headers"] == {"x-api-key": "test-key"}
    assert calls[0][1]["files"]["channel_id"] == (None, "test-channel")
    assert calls[0][1]["files"]["user_info"] == (None, "{}")
    assert calls[0][1]["files"]["thread_id"] != calls[1][1]["files"]["thread_id"]
    message = calls[0][1]["files"]["message"][1]
    assert "JSON Schema" in message
    assert json.dumps(prompt_json_schema(Answer), ensure_ascii=False,
                      separators=(",", ":")) in message

    prepared = requests.Request("POST", calls[0][0],
                                headers=calls[0][1]["headers"],
                                files=calls[0][1]["files"]).prepare()
    content_type = prepared.headers["Content-Type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1].encode()
    assert b"--" + boundary in prepared.body
    for field in (b'channel_id', b'thread_id', b'user_info', b'message'):
        assert b'name="' + field + b'"' in prepared.body


def test_iaedu_retries_invalid_json_but_not_http_errors(monkeypatch):
    responses = iter([stream("não é JSON"), stream('{"ok": true}')])
    monkeypatch.setattr(requests, "post", lambda *a, **kw: next(responses))
    client = IAeduProvider(api_key="secret-test", endpoint="https://example.invalid/api",
                          channel_id="test-channel")
    assert client.generate_structured("pedido", Answer).ok
    assert client.last_failed_outputs == ["não é JSON"]

    response = stream()
    response.status_code = 401
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    monkeypatch.setattr(requests, "post", lambda *a, **kw: response)
    with pytest.raises(LLMError, match="HTTP 401") as error:
        client.generate_structured("pedido", Answer)
    assert "secret-test" not in str(error.value)


def test_iaedu_incomplete_json_has_targeted_retry_and_safe_diagnostics(monkeypatch):
    calls = []
    responses = iter([stream('{"ok":'), stream('{"ok": tru')])

    def post(*args, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(requests, "post", post)
    client = IAeduProvider(api_key="key", endpoint="https://example.invalid/api",
                          channel_id="channel", max_retries=2)
    with pytest.raises(LLMError, match="última causa: incomplete_json") as error:
        client.generate_structured("pedido", Answer)

    diagnostics = error.value.diagnostics
    assert diagnostics["classification"] == "structured_output_exhausted"
    assert [item["category"] for item in diagnostics["attempts"]] == [
        "incomplete_json", "incomplete_json"]
    assert diagnostics["attempts"][0]["output_chars"] == 6
    assert "A resposta terminou antes de fechar o JSON" in calls[1]["files"]["message"][1]
    assert "key" not in json.dumps(diagnostics)
    assert "pedido" not in json.dumps(diagnostics)


def test_iaedu_schema_validation_retry_names_only_invalid_fields(monkeypatch):
    calls = []
    responses = iter([stream('{"wrong": true}'), stream('{"ok": true}')])

    def post(*args, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(requests, "post", post)
    client = IAeduProvider(api_key="key", endpoint="https://example.invalid/api",
                          channel_id="channel", max_retries=2)
    assert client.generate_structured("pedido", Answer).ok
    diagnostic = client.last_structured_output_diagnostics[0]
    assert diagnostic["category"] == "schema_validation"
    assert diagnostic["fields"] == ["ok"]
    assert "falhou o esquema nos campos: ok" in calls[1]["files"]["message"][1]


def test_iaedu_structured_retry_count_from_environment(monkeypatch):
    monkeypatch.setenv("IAEDU_STRUCTURED_MAX_RETRIES", "4")
    client = IAeduProvider(api_key="key", endpoint="https://example.invalid/api",
                          channel_id="channel")
    assert client.max_retries == 4
    assert client.generation_config()["max_retries"] == 4
    with pytest.raises(ValueError, match="at least 1"):
        IAeduProvider(api_key="key", endpoint="https://example.invalid/api",
                      channel_id="channel", max_retries=0)


def test_iaedu_http_error_preserves_safe_detail_and_redacts_credentials(monkeypatch):
    response = requests.Response()
    response.status_code = 401
    response.headers["Content-Type"] = "application/json"
    response._content = b'{"detail":"Invalid API key secret-test"}'
    monkeypatch.setattr(requests, "post", lambda *a, **kw: response)
    client = IAeduProvider(api_key="secret-test", endpoint="https://example.invalid/api",
                          channel_id="test-channel")
    with pytest.raises(LLMError, match="HTTP 401: Invalid API key <redacted>") as error:
        client.generate_text("pedido")
    assert "secret-test" not in str(error.value)
    assert error.value.diagnostics["http_status"] == 401


def test_iaedu_429_respects_retry_after_then_succeeds(monkeypatch):
    responses = iter([
        rate_response(headers={"Retry-After": "7", "X-RateLimit-Remaining-Requests": "0"}),
        stream('{"ok": true}'),
    ])
    sleeps = []
    monkeypatch.setattr(requests, "post", lambda *a, **kw: next(responses))
    client = IAeduProvider(api_key="key", endpoint="https://example.invalid/api",
                          channel_id="channel", rate_limit_max_retries=2,
                          sleep_fn=sleeps.append)
    assert client.generate_structured("pedido", Answer).ok
    assert sleeps == [7.0]
    assert client.last_rate_limit_attempts[0]["limit_kind"] == "requests"
    assert client.last_rate_limit_attempts[0]["headers"]["retry-after"] == "7"


def test_iaedu_429_without_retry_after_uses_exponential_backoff(monkeypatch):
    responses = iter([rate_response(), rate_response(), stream('{"ok": true}')])
    sleeps = []
    monkeypatch.setattr(requests, "post", lambda *a, **kw: next(responses))
    client = IAeduProvider(api_key="key", endpoint="https://example.invalid/api",
                          channel_id="channel", rate_limit_max_retries=2,
                          rate_limit_base_delay=2, rate_limit_jitter=0,
                          sleep_fn=sleeps.append)
    assert client.generate_structured("pedido", Answer).ok
    assert sleeps == [2.0, 4.0]


def test_iaedu_429_retry_exhaustion_preserves_attempts(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **kw: rate_response())
    sleeps = []
    client = IAeduProvider(api_key="key", endpoint="https://example.invalid/api",
                          channel_id="channel", rate_limit_max_retries=2,
                          rate_limit_base_delay=1, rate_limit_jitter=0,
                          sleep_fn=sleeps.append)
    with pytest.raises(LLMError, match="rate limit") as error:
        client.generate_text("pedido")
    assert sleeps == [1.0, 2.0]
    assert error.value.diagnostics["classification"] == "retry_exhausted"
    assert len(error.value.diagnostics["attempts"]) == 3


def test_iaedu_permanent_quota_exhaustion_does_not_retry(monkeypatch):
    post = Mock(return_value=rate_response(
        detail="insufficient_quota: daily quota exceeded", stream_event=True))
    monkeypatch.setattr(requests, "post", post)
    sleeps = []
    client = IAeduProvider(api_key="key", endpoint="https://example.invalid/api",
                          channel_id="channel", rate_limit_max_retries=5,
                          sleep_fn=sleeps.append)
    with pytest.raises(LLMError) as error:
        client.generate_text("pedido")
    assert post.call_count == 1
    assert sleeps == []
    assert error.value.diagnostics["classification"] == "quota_exhausted"


def test_parser_skips_nonmatching_json_object_before_payload():
    result = _parse_json_object(
        '{"type": "illustration"}\n```json\n{"ok": true}\n```', Answer
    )
    assert result.ok


def test_prompt_schema_drops_metadata_but_keeps_real_title_property():
    schema = prompt_json_schema(ProposerWireProposal)
    add = schema["$defs"]["ProposerWireAdd"]
    assert "title" not in add  # generated model title metadata
    assert "title" in add["properties"]  # actual add-operation field
    assert all("default" not in field for field in add["properties"].values())


def test_change_schema_exposes_existing_operation_specific_constraints():
    schema = Change.model_json_schema()
    assert schema["allOf"][0]["then"]["properties"]["category"] == {"type": "null"}


def test_ollama_schema_request(monkeypatch):
    response = Mock()
    response.json.return_value = {"response": '{"ok": true}'}
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "post", post)
    assert OllamaProvider(model="test-model").generate_structured("pedido", Answer).ok
    assert post.call_args.kwargs["json"]["format"] == Answer.model_json_schema()
    assert post.call_args.kwargs["json"]["model"] == "test-model"


def test_provider_selection(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "iaedu")
    monkeypatch.setenv("CRITIC_LLM_PROVIDER", "ollama")
    assert get_provider().name == "iaedu"
    assert get_provider(role="CRITIC").name == "ollama"
