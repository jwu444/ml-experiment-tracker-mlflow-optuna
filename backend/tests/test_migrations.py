"""Guards on the migration history. These run on SQLite like everything else;
the Postgres-specific upgrade/downgrade cycle is verified manually in this
task's steps, because CI has no Postgres service."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "backend" / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_migration_history_has_exactly_one_head() -> None:
    # Two heads means someone branched the history without merging it.
    assert len(_script_directory().get_heads()) == 1


def test_every_orm_table_is_reachable_from_the_head() -> None:
    # Cheap drift guard: a model added without a migration fails here.
    from app.models import Base

    revisions = list(_script_directory().walk_revisions())
    sources = "\n".join((Path(rev.path).read_text() if rev.path else "") for rev in revisions)
    for table_name in Base.metadata.tables:
        bare = table_name.split(".")[-1]
        assert bare in sources, f"{bare} has no migration"
