"""The deploy manifest is a config file with load-bearing properties, so the
ones that fail silently in production are pinned here rather than discovered
on Render."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Render's own service types. A static site is NOT one of them — it is a `web`
# service with `runtime: static`, so both services here share a type and must be
# told apart by runtime. Selecting on type alone returns whichever comes first.
RENDER_SERVICE_TYPES = {"web", "worker", "cron", "pserv"}


def _manifest():
    return yaml.safe_load((ROOT / "render.yaml").read_text())


def _service(manifest, runtime):
    return next(s for s in manifest["services"] if s.get("runtime") == runtime)


def test_render_declares_both_services_and_a_database():
    manifest = _manifest()
    runtimes = {service.get("runtime") for service in manifest["services"]}
    assert {"docker", "static"} <= runtimes
    assert manifest.get("databases")


def test_every_service_type_is_one_render_actually_has():
    """Render rejects the ENTIRE blueprint on an unknown type, so a typo here
    creates nothing at all. `type: static` shipped once and got exactly this
    far: the manifest parsed as YAML, every other test passed, and it failed at
    the first Blueprint that read it."""
    for service in _manifest()["services"]:
        assert service["type"] in RENDER_SERVICE_TYPES, service


def test_the_api_service_declares_a_health_check_path():
    """Render restarts an unhealthy instance. Without this it restarts nothing,
    and a wedged process serves 502s indefinitely."""
    assert _service(_manifest(), "docker")["healthCheckPath"] == "/health"


def test_mlflow_db_upgrade_runs_before_the_server_binds():
    """Free-tier services reject preDeployCommand, which is where this used to
    live, so the migrations run at container start instead — but they must still
    complete BEFORE uvicorn serves traffic, or the first request races a store
    that is not there yet. The entrypoint is what orders that; `exec` is what
    makes uvicorn the container's main process rather than a child of a shell
    that no longer forwards signals to it."""
    api = _service(_manifest(), "docker")
    assert "preDeployCommand" not in api, "free tier rejects it; the blueprint will not validate"
    assert "mlflow" not in api.get("startCommand", "")

    entrypoint = (ROOT / "docker-entrypoint.sh").read_text()
    prepare = entrypoint.index("prepare_mlflow_store.py")
    serve = entrypoint.index("exec uvicorn")
    assert prepare < serve, "the store must be prepared before the server binds"

    assert "docker-entrypoint.sh" in (ROOT / "Dockerfile").read_text()


def test_the_dockerfile_does_not_bake_secrets_or_the_artifact_store():
    text = (ROOT / "Dockerfile").read_text()
    assert "ANTHROPIC_API_KEY" not in text
    assert "VOYAGE_API_KEY" not in text
    assert "mlruns" not in text  # 126 MB of artifacts do not belong in an image


def test_the_static_service_declares_the_api_base_and_builds_deterministically():
    """VITE_API_BASE is inlined at build time (frontend/src/api.ts), so a value
    set only in the Render dashboard after the fact does nothing — it must be
    declared here. Unset, the bundle falls back to the relative /api, which
    resolves against the static site's own origin and its /* rewrite answers
    every API call with index.html and a 200: no error, just no data.
    npm ci (not npm install) is what makes the build fail loudly on a
    lock/package.json mismatch instead of silently re-resolving versions."""
    web = _service(_manifest(), "static")
    keys = {v["key"] for v in web.get("envVars", [])}
    assert "VITE_API_BASE" in keys
    assert "npm ci" in web["buildCommand"]


def test_env_example_documents_every_deploy_variable():
    """A variable that exists only in the Render dashboard is one the next
    person cannot know to set."""
    text = (ROOT / ".env.example").read_text()
    for key in (
        "CORS_ALLOW_ORIGINS",
        "MLFLOW_TRACKING_URI",
        "MLFLOW_ARTIFACT_ROOT",
        "MLFLOW_S3_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
        assert key in text, key
