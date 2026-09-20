"""Pure string rewriting, tested offline. The SQL that applies it is four
lines; the arithmetic of which prefix becomes which is where this goes wrong,
and a wrong URI fails as a file-not-found for a file that uploaded fine."""

import pytest
from migrate_artifact_uris import _TABLES, plan_rewrites, rewrite_uri

OLD = "file:///Users/x/dev/wavepoint/mlruns"
NEW = "s3://wavepoint-artifacts/mlruns"


def test_it_replaces_only_the_root_prefix():
    got = rewrite_uri(f"{OLD}/12/abc123/artifacts", old_root=OLD, new_root=NEW)
    assert got == f"{NEW}/12/abc123/artifacts"


def test_a_bare_relative_root_is_matched_too():
    """mlflow_artifact_root defaults to './mlruns', so rows written before any
    deploy carry a relative path, not a file:// URI."""
    got = rewrite_uri("./mlruns/12/abc/artifacts", old_root="./mlruns", new_root=NEW)
    assert got == f"{NEW}/12/abc/artifacts"


def test_a_uri_already_under_the_new_root_is_left_alone():
    """The script must be safe to re-run — a half-finished migration is the
    likeliest state to find it in."""
    already = f"{NEW}/12/abc/artifacts"
    assert rewrite_uri(already, old_root=OLD, new_root=NEW) == already


def test_a_uri_under_neither_root_is_refused_not_guessed():
    """Silently leaving it makes the run unloadable with no error; silently
    rewriting it invents a path. Naming it is the only honest option."""
    with pytest.raises(ValueError, match="unexpected"):
        rewrite_uri("s3://someone-elses-bucket/12/abc", old_root=OLD, new_root=NEW)


def test_the_plan_skips_rows_that_need_no_change():
    rows = [("run-1", f"{OLD}/1/a"), ("run-2", f"{NEW}/1/b")]
    plan = plan_rewrites(rows, old_root=OLD, new_root=NEW)
    assert plan == [("run-1", f"{NEW}/1/a")]


def test_the_plan_preserves_the_trailing_path_exactly():
    """The suffix carries the experiment id, the run id and 'artifacts'. Losing
    a segment points every run at the same directory."""
    rows = [("r", f"{OLD}/7/deadbeef/artifacts")]
    assert plan_rewrites(rows, old_root=OLD, new_root=NEW)[0][1].endswith("/7/deadbeef/artifacts")


def test_a_root_that_only_shares_a_string_prefix_is_not_matched():
    """ "./mlruns-backup" shares a string prefix with "./mlruns" but is not a
    path underneath it. A bare str.startswith would rewrite it into a
    fabricated s3:// URI for data this script was never told about; the
    honest response is the same refusal as any other unrelated root."""
    with pytest.raises(ValueError, match="unexpected"):
        rewrite_uri("./mlruns-backup/12/x/artifacts", old_root="./mlruns", new_root=NEW)


def test_a_new_root_string_prefix_sibling_is_not_already_migrated():
    """The same boundary applies to the "already migrated" check: a uri that
    merely shares NEW's characters as a string prefix — without NEW being an
    actual path ancestor — must not be waved through unchanged. It belongs to
    neither root, so it is refused rather than silently accepted."""
    sibling = f"{NEW}-backup/12/x/artifacts"
    with pytest.raises(ValueError, match="unexpected"):
        rewrite_uri(sibling, old_root=OLD, new_root=NEW)


def test_all_three_mlflow_artifact_columns_are_covered():
    """MLflow 3.x stores absolute artifact URIs in three places, not two: a
    logged model's own artifact_location (mlruns/models/m-<id>/artifacts) is
    separate from its run's artifact_uri, and routes/runs.py loads models
    through it via `runs:/{run_id}/model`. Pinning the tuple's exact contents
    means deleting an entry fails this test instead of silently leaving every
    trained model unreachable after a migration that reports success."""
    assert _TABLES == (
        ("mlflow.experiments", "experiment_id", "artifact_location"),
        ("mlflow.runs", "run_uuid", "artifact_uri"),
        ("mlflow.logged_models", "model_id", "artifact_location"),
    )
