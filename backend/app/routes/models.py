"""GET /models — the training registry, for the frontend's form to read (issue #52).

The single source of truth stays `training.MODEL_REGISTRY`; this module only
serializes it. Never hand-maintain a second copy of this list anywhere in the
frontend — that mismatch is exactly how #51 happened.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import HyperparamSpecOut, ModelSpecOut
from app.training import MODEL_REGISTRY

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelSpecOut])
def list_models() -> list[ModelSpecOut]:
    out = []
    for model_type, spec in MODEL_REGISTRY.items():
        hyperparams = [
            HyperparamSpecOut(name=name, type=kind, min=lo, max=hi, log_scale=log)
            for name, (kind, lo, hi, log) in spec.search_space.items()
        ]
        out.append(
            ModelSpecOut(
                model_type=model_type,
                task_type=spec.task_type,
                # An empty search space is the registry saying nothing about
                # this model is tunable — POST /experiments/{id}/tune 422s on
                # it (D25), so the form must not offer Tune.
                tunable=bool(spec.search_space),
                hyperparams=hyperparams,
                column_hyperparams=list(spec.column_hyperparams),
            )
        )
    return out
