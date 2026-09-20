from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import findings
from app.config import settings
from app.dataset_io import decode_csv, hash_csv, load_csv
from app.db import get_session
from app.loop import run_loop
from app.models import Dataset, DatasetColumn
from app.profiler import profile_dataframe
from app.schemas import DatasetColumnOut, DatasetDetailOut, DatasetOut, FindingCreatedOut

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _find_by_hash(session: Session, content_hash: str) -> Dataset | None:
    """Find a dataset by its content hash."""
    return session.execute(
        select(Dataset).where(Dataset.content_hash == content_hash)
    ).scalar_one_or_none()


@router.post("", response_model=DatasetOut)
def upload_dataset(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> Dataset:
    raw = file.file.read()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File exceeds size limit")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    content_hash = hash_csv(raw)

    # Idempotent upload: known content short-circuits before any parsing/profiling.
    existing = _find_by_hash(session, content_hash)
    if existing is not None:
        return existing

    try:
        data_csv = decode_csv(raw)
        df = load_csv(data_csv)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}") from exc
    if df.empty:
        raise HTTPException(status_code=400, detail="CSV has no rows")
    if len(df) > settings.max_rows:
        raise HTTPException(status_code=413, detail="CSV exceeds row limit")

    dataset = Dataset(
        name=file.filename or "dataset.csv",
        n_rows=int(len(df)),
        n_cols=int(df.shape[1]),
        profile_json=profile_dataframe(
            df,
            sample_rows=settings.profile_sample_rows,
            max_cardinality=settings.profile_max_cardinality,
            max_corr_cols=settings.profile_max_corr_cols,
            top_corr_pairs=settings.profile_top_corr_pairs,
            token_budget=settings.profile_token_budget,
        ),
        data_csv=data_csv,
        content_hash=content_hash,
    )
    try:
        session.add(dataset)
        session.flush()
        for ordinal_position, col in enumerate(dataset.profile_json["columns"]):
            dataset_column = DatasetColumn(
                dataset_id=dataset.id,
                name=col["name"],
                ordinal_position=ordinal_position,
                inferred_type=col["dtype"],
                null_count=col["n_null"],
            )
            session.add(dataset_column)
        session.commit()
    except IntegrityError:
        # A concurrent upload won the race on the unique hash — return the winner.
        session.rollback()
        winner = _find_by_hash(session, content_hash)
        if winner is None:
            raise
        return winner
    session.refresh(dataset)
    return dataset


@router.get("", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_session)) -> list[DatasetOut]:
    # Project only the columns needed for DatasetOut — avoid hydrating data_csv
    # (raw CSV text, potentially multi-MB per row) and profile_json on this hot
    # path (the sidebar self-fetches on every AppShell mount).
    rows = session.execute(
        select(Dataset.id, Dataset.name, Dataset.n_rows, Dataset.n_cols).order_by(
            Dataset.created_at.desc()
        )
    ).all()
    return [DatasetOut(id=r.id, name=r.name, n_rows=r.n_rows, n_cols=r.n_cols) for r in rows]


@router.get("/{dataset_id}", response_model=DatasetDetailOut)
def get_dataset(dataset_id: str, session: Session = Depends(get_session)) -> DatasetDetailOut:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    # Ordered by ordinal_position, i.e. the order the columns appeared in the
    # uploaded CSV — a form's dropdowns should read like the file does.
    columns = session.execute(
        select(DatasetColumn)
        .where(DatasetColumn.dataset_id == dataset_id)
        .order_by(DatasetColumn.ordinal_position)
    ).scalars()
    return DatasetDetailOut(
        id=dataset.id,
        name=dataset.name,
        n_rows=dataset.n_rows,
        n_cols=dataset.n_cols,
        columns=[DatasetColumnOut.model_validate(c) for c in columns],
    )


EDA_QUESTION = (
    "Perform exploratory data analysis on this dataset. Describe the distribution of the "
    "key numeric columns, the coverage of each group (for example, rows per ticker), and "
    "the correlation structure between the candidate features and the target. Call out "
    "anything a modeller should know before fitting: skew, gaps, outliers, or columns that "
    "look like leakage. Be specific and quantitative."
)


@router.post("/{dataset_id}/eda", status_code=201, response_model=FindingCreatedOut)
def run_eda(dataset_id: str, session: Session = Depends(get_session)) -> FindingCreatedOut:
    """Generate a reviewable EDA write-up for one dataset (2b.1).

    Calls `run_loop` synchronously, exactly as `/chats` does — no new LLM
    machinery (D19/D23). Charts are rendered for the judge and discarded; only
    the findings text persists.
    """
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = load_csv(dataset.data_csv)
    profile = profile_dataframe(
        df,
        sample_rows=settings.profile_sample_rows,
        max_cardinality=settings.profile_max_cardinality,
        max_corr_cols=settings.profile_max_corr_cols,
        top_corr_pairs=settings.profile_top_corr_pairs,
        token_budget=settings.profile_token_budget,
    )
    # Deliberately NOT wrapped: `/chats` lets a loop failure propagate, and this
    # endpoint uses the same mapping (§6). The "no partial finding" guarantee
    # comes from ordering, not from a handler — create_finding is below the loop,
    # so a failure leaves nothing half-generated in the review queue.
    result = run_loop(
        [{"id": dataset.id, "name": dataset.name, "profile": profile}],
        {dataset.id: df},
        [],
        EDA_QUESTION,
    )

    row = findings.create_finding(session, "eda", dataset.id, result.interpretation)
    session.commit()
    session.refresh(row)
    return FindingCreatedOut(
        finding_id=row.id,
        source_type=row.source_type,
        source_id=row.source_id,
        status=row.status,
        text=row.text,
    )
