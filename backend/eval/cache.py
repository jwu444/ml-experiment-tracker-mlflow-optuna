"""A caching stand-in for the Voyage client, used only by the eval harness.

The free tier allows 3 requests per minute. An uncached 20-query run is about
seven minutes of forced backoff, which means it does not get run; the
nine-configuration sweep (D46) would be unusable. Query text is identical
across configurations, so after the first run the sweep costs no Voyage calls
at all.

This is a CLIENT SHIM, not a change to `app.retrieval`.
`retrieval.search_runs(..., client=...)` already threads its client down to
`embeddings.embed_texts`, whose only requirement is
`.embed(texts, model=, input_type=, output_dimension=) -> obj.embeddings`.
Satisfying that contract keeps the whole cache inside the eval package and
leaves the production path — including its width check and its 429 retry —
exercised exactly as it is in a live request.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Response:
    """Mimics the Voyage SDK's response object; `embed_texts` reads only this."""

    embeddings: list[list[float]]


def cache_key(model: str, input_type: str, text: str) -> str:
    """The model name is IN the key.

    Two models' vectors are not comparable (D14), so changing `voyage_model`
    must miss and refetch. Keying on the text alone would silently serve the
    previous model's vectors, and the only symptom would be eval numbers that
    nobody can attribute.

    `input_type` is in the key for the same reason: Voyage's models are trained
    with the document/query asymmetry (D29), and the two vectors for one string
    are different vectors.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{model}|{input_type}|{digest}"


class CachingVoyageClient:
    """Reads vectors from a JSON file; delegates misses to `inner`."""

    def __init__(self, path: Path, inner: Any | None = None) -> None:
        self.path = Path(path)
        self.inner = inner
        self.hits = 0
        self.misses = 0
        self._vectors: dict[str, list[float]] = self._load()

    def _load(self) -> dict[str, list[float]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            # A half-written file must cost a slow run, never a crash that
            # presents as a retrieval bug.
            logger.warning("ignoring unreadable vector cache at %s", self.path)
            return {}
        return {k: [float(x) for x in v] for k, v in data.items()}

    def embed(
        self, texts: list[str], *, model: str, input_type: str, output_dimension: int
    ) -> _Response:
        keys = [cache_key(model, input_type, t) for t in texts]
        missing = [t for t, key in zip(texts, keys, strict=True) if key not in self._vectors]

        if missing:
            if self.inner is None:
                raise RuntimeError(
                    f"vector cache has no inner client and {len(missing)} text(s) are uncached"
                )
            fresh = self.inner.embed(
                missing, model=model, input_type=input_type, output_dimension=output_dimension
            )
            for text, vector in zip(missing, fresh.embeddings, strict=True):
                self._vectors[cache_key(model, input_type, text)] = [float(v) for v in vector]
            # Persist immediately: a 20-minute cold run at the free tier's 3
            # RPM dies to a single transient error just as often as it
            # succeeds, and a save-at-the-end cache would discard every
            # vector paid for so far. Saving here, inside the same call that
            # just wrote them into `self._vectors`, means a crash on the NEXT
            # query's request still leaves this query's vector on disk.
            self.save()

        self.misses += len(missing)
        self.hits += len(texts) - len(missing)
        # Rebuilt from the keys so the output order matches the INPUT order; a
        # transposition here would mislabel every query's vector.
        return _Response(embeddings=[self._vectors[key] for key in keys])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._vectors))
