"""Per-question execution context; contains no Agent or optimization policy."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import time


_tags = ContextVar("model_tags", default={})


@contextmanager
def event_scope(**tags):
    token = _tags.set({**_tags.get(), **tags})
    try:
        yield
    finally:
        _tags.reset(token)


_scope = ContextVar("model_execution", default=None)


@contextmanager
def execution_scope(*, emit, deadline=None, media_cache=None, media_slots=None):
    context = dict(emit=emit, deadline=deadline, media_slots=media_slots,
                   media_cache=media_cache, leases=[], calls=0)
    token = _scope.set(context)
    try:
        yield context
    finally:
        for lease in context["leases"]:
            lease.close()
        _scope.reset(token)


def current_scope():
    return _scope.get()


def _safe_event(value):
    if isinstance(value, dict):
        return {k: _safe_event(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_event(v) for v in value]
    if isinstance(value, str) and value.startswith("data:"):
        return {"media_sha256": hashlib.sha256(value.encode()).hexdigest(), "encoded_chars": len(value)}
    return value


def emit_event(kind, **fields):
    context = _scope.get()
    if context:
        context["emit"](_safe_event({"kind": kind, "time": time.time(), **_tags.get(), **fields}))


def remaining_timeout(default):
    context = _scope.get()
    if context and context["deadline"] is not None:
        remaining = context["deadline"] - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Question deadline exceeded")
        return min(default, remaining)
    return default


def output_metrics(events):
    """Response counts, distinct from residual invalid actions and task scores."""
    invalid = [event for event in events if event["kind"] == "structured_invalid"]
    return {
        "invalid_model_outputs": len(invalid),
        "invalid_text_outputs": sum(e["modality"] == "text" for e in invalid),
        "invalid_visual_outputs": sum(e["modality"] in ("image", "video") for e in invalid),
        "structured_repairs": sum(e["kind"] == "structured_repair" for e in events),
        "structured_repairs_succeeded": sum(e["kind"] == "structured_repair_succeeded" for e in events),
        "length_responses": sum(e["kind"] == "model_response" and e.get("finish_reason") == "length" for e in events),
    }
