"""Contrato HTTP dos fornecedores sem chamadas externas nem consumo de tokens."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from llm import IAeduProvider, LLMError, OllamaProvider, get_provider  # noqa: E402


class Answer(BaseModel):
    ok: bool


def stream(*contents):
    response = Mock()
    response.iter_lines.return_value = [json.dumps({"type": "token", "content": part}).encode()
                                        for part in contents]
    response.raise_for_status.return_value = None
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
    assert "JSON Schema" in calls[0][1]["files"]["message"][1]

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

    response = stream()
    response.status_code = 401
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    monkeypatch.setattr(requests, "post", lambda *a, **kw: response)
    with pytest.raises(LLMError, match="HTTP 401") as error:
        client.generate_structured("pedido", Answer)
    assert "secret-test" not in str(error.value)


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
