"""Local OpenAI-compatible embedding requests, independent of Agent policy."""
from dataclasses import asdict, dataclass
import json
import math
import urllib.request

import numpy as np

from .execution import emit_event, remaining_timeout
from .pool import canonical_endpoint


@dataclass(frozen=True)
class EmbeddingConfig:
    endpoint: str
    model: str
    timeout_sec: float = 60

    def __post_init__(self):
        if not isinstance(self.endpoint, str):
            raise ValueError('Embedding endpoint must be a local URL')
        object.__setattr__(self, 'endpoint', canonical_endpoint(self.endpoint))
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError('Embedding model must be nonempty')
        object.__setattr__(self, 'model', self.model.strip())
        if (type(self.timeout_sec) not in (int, float)
                or not math.isfinite(self.timeout_sec) or self.timeout_sec <= 0):
            raise ValueError('Embedding timeout_sec must be finite and positive')

    @classmethod
    def from_dict(cls, data):
        if (not isinstance(data, dict) or set(data) - {'endpoint', 'model', 'timeout_sec'}
                or not {'endpoint', 'model'} <= set(data)):
            raise ValueError('embedding requires endpoint/model and optional timeout_sec')
        return cls(**data)

    def to_dict(self):
        return asdict(self)


def embed(config: EmbeddingConfig, texts: tuple[str, ...]) -> np.ndarray:
    """Validate ordering/shape and normalize once for cosine similarity. No fallback."""
    if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
        raise ValueError('Embedding inputs must be nonempty strings')
    request = urllib.request.Request(config.endpoint + '/embeddings',
        data=json.dumps(dict(model=config.model, input=list(texts), encoding_format='float')).encode(),
        headers={'Content-Type': 'application/json'})
    emit_event('embedding_request', model=config.model, endpoint=config.endpoint,
               input_count=len(texts), input_chars=[len(t) for t in texts])
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                request, timeout=remaining_timeout(config.timeout_sec)) as response:
            payload = json.load(response)
        if payload.get('model') != config.model:
            raise ValueError('Embedding response model mismatch')
        rows = payload['data']
        if (len(rows) != len(texts) or any(type(r['index']) is not int for r in rows)
                or sorted(r['index'] for r in rows) != list(range(len(texts)))):
            raise ValueError('Embedding response indexes mismatch')
        vectors = np.asarray([r['embedding'] for r in sorted(rows, key=lambda r:r['index'])], dtype=np.float64)
        if vectors.ndim != 2 or not vectors.shape[1] or not np.isfinite(vectors).all():
            raise ValueError('Invalid embedding vectors')
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.isfinite(norms).all() or np.any(norms == 0):
            raise ValueError('Invalid embedding norms')
        vectors /= norms
        vectors.flags.writeable = False
        emit_event('embedding_response', model=config.model, input_count=len(texts),
                   dimensions=vectors.shape[1], usage=payload.get('usage'))
        return vectors
    except Exception as exc:
        emit_event('embedding_error', model=config.model, error=str(exc))
        raise
