"""The Alembic env runs autogenerate with include_schemas=True, which makes it
consider every schema in the database. MLflow owns the `mlflow` schema (design
D4) and manages it with its own migrations — without a filter, autogenerate
would propose dropping all of MLflow's tables."""

from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[1] / "alembic" / "env.py"


def _load_filter():
    # env.py runs migrations at import time, so exec just the filter rather than
    # importing the module. The slice starts at _OWNED_SCHEMAS because the filter
    # closes over it, and ends at the first def that follows the filter itself.
    source = _ENV_PATH.read_text()
    start = source.index("_OWNED_SCHEMAS = {")
    filter_start = source.index("def app_schema_only(", start)
    end = source.index("\ndef ", filter_start + 1)
    namespace: dict[str, object] = {}
    exec(compile(source[start:end], str(_ENV_PATH), "exec"), namespace)
    return namespace["app_schema_only"]


class _FakeTable:
    def __init__(self, schema: str | None) -> None:
        self.schema = schema


def test_app_schema_tables_are_included() -> None:
    keep = _load_filter()
    assert keep(_FakeTable("app"), "runs", "table", True, None) is True


def test_mlflow_schema_tables_are_excluded() -> None:
    keep = _load_filter()
    # MLflow's own tables — autogenerate must never touch these.
    assert keep(_FakeTable("mlflow"), "runs", "table", True, None) is False
    assert keep(_FakeTable("mlflow"), "alembic_version", "table", True, None) is False


def test_unschemaed_tables_are_excluded() -> None:
    # env.py no longer uses schema_translate_map (see its module docstring): on
    # SQLite the "app" schema is a real ATTACHed database now, so our own tables
    # report schema="app" there too, exactly as on Postgres. schema=None is no
    # longer a state our own tables can be in — only alembic's own bookkeeping
    # table (created outside target_metadata) reports it, and that must stay
    # excluded from the app-schema comparison.
    keep = _load_filter()
    assert keep(_FakeTable(None), "runs", "table", True, None) is False


def test_non_table_objects_are_always_included() -> None:
    # Columns/indexes are filtered by their parent table, not individually.
    keep = _load_filter()
    assert keep(_FakeTable("mlflow"), "some_column", "column", True, None) is True
