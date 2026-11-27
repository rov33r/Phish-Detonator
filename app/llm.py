"""Vultr Serverless Inference client (SPEC 6.3, 6.5). The only module that talks to a model.

Every call asks for strict JSON (`json_schema`), retries rate limits and server errors,
falls back to `PD_MODEL_FALLBACK`, and repairs invalid output once.

Strict schemas: list every property in `required`, set `additionalProperties: false`,
and use `["string", "null"]` for optional values.
"""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Any, Callable, NamedTuple

import openai

BASE_URL = "https://api.vultrinference.com/v1"
MAX_ATTEMPTS = 3
BACKOFF_S = (1.0, 2.0, 4.0)
MAX_RETRY_AFTER_S = 10.0

Validator = Callable[[dict], None]  # raises ValueError with a short message on a miss

_client: Any = None
_sleep = time.sleep  # replaced in tests


class LLMError(RuntimeError):
    """No usable answer: bad key, every model down, or a request the API rejects."""


class InvalidOutput(LLMError):
    """The model answered twice with JSON that does not parse or fails validation."""


class Reply(NamedTuple):
    data: dict
    model: str


class _Unavailable(Exception):
    """This model is out for now (rate limit, 5xx, not found); try the next one."""


def client():
    global _client
    if _client is None:
        key = os.environ.get("VULTR_INFERENCE_KEY")
        if not key:
            raise LLMError("VULTR_INFERENCE_KEY is not set")
        _client = openai.OpenAI(base_url=BASE_URL, api_key=key, max_retries=0, timeout=60)
    return _client


def chat_json(
    messages: list[dict],
    schema: dict,
    *,
    name: str,
    effort: str | None = "low",
    max_tokens: int = 1024,
    validate: Validator | None = None,
    model: str | None = None,
) -> Reply:
    """One JSON answer from the first model that works. `effort`: low for agent steps,
    medium for the investigator (SPEC 6.5)."""
    models = _dedupe([model, os.environ.get("PD_MODEL"), os.environ.get("PD_MODEL_FALLBACK")])
    return _first_working(models, messages, schema, name, effort, max_tokens, validate)


def vision_json(
    prompt: str,
    png: bytes,
    schema: dict,
    *,
    name: str,
    validate: Validator | None = None,
) -> Reply:
    """Brand check (SPEC 8.3): the screenshot goes to `PD_VISION_MODEL`. Without one, or if
    it is down, the same prompt goes to the text models without the image."""
    vision_model = os.environ.get("PD_VISION_MODEL")
    if vision_model:
        image = "data:image/png;base64," + base64.b64encode(png).decode()
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image}}]
        try:
            return _first_working([vision_model], [{"role": "user", "content": content}],
                                  schema, name, "low", 512, validate)
        except LLMError:
            pass
    return chat_json([{"role": "user", "content": prompt}], schema, name=name,
                     max_tokens=512, validate=validate)


def untrusted(text: str) -> str:
    """Wrap page-derived text (CLAUDE.md rule 5). A closing tag inside the page is defused."""
    safe = text.replace("</untrusted_page", "&lt;/untrusted_page")
    return f"<untrusted_page>\n{safe}\n</untrusted_page>"


def parse_json(content: str) -> dict:
    """Parse one JSON object, tolerating code fences and text around it."""
    text = content.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in the answer")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e.msg} at char {e.pos}") from None
    if not isinstance(data, dict):
        raise ValueError("the answer is not a JSON object")
    return data


def _first_working(models, messages, schema, name, effort, max_tokens, validate) -> Reply:
    if not models:
        raise LLMError("no model configured (set PD_MODEL)")
    for model in models:
        try:
            return _answer(model, messages, schema, name, effort, max_tokens, validate)
        except _Unavailable:
            continue
    raise LLMError(f"no model answered: {', '.join(models)}")


def _answer(model, messages, schema, name, effort, max_tokens, validate) -> Reply:
    content = _complete(model, messages, schema, name, effort, max_tokens)
    try:
        return Reply(_checked(content, validate), model)
    except ValueError as e:
        repair = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": f"That answer was invalid: {e}. "
                                        "Answer with one JSON object only, matching the schema."},
        ]
    content = _complete(model, repair, schema, name, effort, max_tokens)
    try:
        return Reply(_checked(content, validate), model)
    except ValueError as e:
        raise InvalidOutput(f"{model}: {e}") from None


def _checked(content: str, validate: Validator | None) -> dict:
    data = parse_json(content)
    if validate:
        validate(data)
    return data


def _complete(model, messages, schema, name, effort, max_tokens) -> str:
    plain = False  # after a 400: json_object and no reasoning setting
    attempt = 0
    while attempt < MAX_ATTEMPTS:
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_completion_tokens": max_tokens}
        if plain:
            kwargs["response_format"] = {"type": "json_object"}
        else:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            }
            if effort:
                kwargs["extra_body"] = {"reasoning_effort": effort}
        try:
            resp = client().chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except openai.BadRequestError as e:
            if plain:
                raise LLMError(f"{model} rejected the request: {e.message}") from None
            plain = True
            continue
        except openai.AuthenticationError:
            raise LLMError("inference key rejected (401)") from None
        except openai.RateLimitError as e:
            _sleep(_retry_after(e))
        except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError):
            _sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
        except (openai.NotFoundError, openai.PermissionDeniedError):
            raise _Unavailable from None
        except openai.APIStatusError as e:
            if e.status_code == 402:
                raise _Unavailable from None
            raise LLMError(f"{model}: HTTP {e.status_code}") from None
        attempt += 1
    raise _Unavailable


def _retry_after(e: openai.APIStatusError) -> float:
    try:
        wait = float(e.response.headers.get("retry-after", "1"))
    except ValueError:
        wait = 1.0
    return max(0.0, min(wait, MAX_RETRY_AFTER_S))


def _dedupe(items: list[str | None]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
