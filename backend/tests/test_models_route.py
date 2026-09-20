from app.training import MODEL_REGISTRY


def test_get_models_lists_every_registry_entry(client) -> None:
    resp = client.get("/models")

    assert resp.status_code == 200
    body = {m["model_type"]: m for m in resp.json()}
    # Parametrized over the registry itself, so adding a model to
    # MODEL_REGISTRY without exposing it here is a failing test rather than a
    # model the frontend can never pick (#51).
    assert set(body) == set(MODEL_REGISTRY)


def test_persistence_is_reported_as_not_tunable(client) -> None:
    body = {m["model_type"]: m for m in client.get("/models").json()}
    assert body["persistence"]["tunable"] is False
    assert body["persistence"]["hyperparams"] == []


def test_persistence_declares_its_column_hyperparam(client) -> None:
    # Nothing to tune, but it still cannot fit without `prior_column` — a form
    # that only read `hyperparams` would submit a run guaranteed to FAIL.
    body = {m["model_type"]: m for m in client.get("/models").json()}
    assert body["persistence"]["column_hyperparams"] == ["prior_column"]
    assert body["ridge"]["column_hyperparams"] == []


def test_ridge_reports_its_search_space(client) -> None:
    body = {m["model_type"]: m for m in client.get("/models").json()}
    ridge = body["ridge"]
    assert ridge["tunable"] is True
    assert ridge["hyperparams"] == [
        {"name": "alpha", "type": "float", "min": 1e-3, "max": 1e3, "log_scale": True}
    ]
