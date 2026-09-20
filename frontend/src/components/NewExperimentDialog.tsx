import { useEffect, useState } from "react";
import { createExperiment, getDataset, listDatasets } from "../api";
import type { DatasetColumn, DatasetOut, ExperimentRow } from "../types";
import ErrorBanner from "./ErrorBanner";
import { Button, Dialog, Input, Textarea } from "../ui";
import styles from "./DialogForm.module.css";

interface NewExperimentDialogProps {
  onCreated: (experiment: ExperimentRow) => void;
}

/** Start an investigation (#52). `target_column` and `task_type` are fixed here
 *  and inherited by every run inside it (D34) — which is what makes the runs
 *  comparable, and why this form, not the run form, asks for them. */
export default function NewExperimentDialog({ onCreated }: NewExperimentDialogProps) {
  const [open, setOpen] = useState(false);
  const [datasets, setDatasets] = useState<DatasetOut[] | null>(null);
  const [columns, setColumns] = useState<DatasetColumn[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [taskType, setTaskType] = useState("regression");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (!open || datasets !== null) return;
    let active = true;
    listDatasets()
      .then((rows) => {
        if (!active) return;
        setDatasets(rows);
        setDatasetId((prev) => prev || (rows[0]?.id ?? ""));
      })
      .catch((err: unknown) => {
        if (active) setFailure(err instanceof Error ? err.message : "Could not load datasets");
      });
    return () => {
      active = false;
    };
  }, [open, datasets]);

  // The target has to come from the chosen dataset's real columns: a typo'd
  // target is a 422 at every later train, on an experiment already created.
  useEffect(() => {
    if (!datasetId) return;
    let active = true;
    getDataset(datasetId)
      .then((dataset) => {
        if (!active) return;
        setColumns(dataset.columns);
        setTargetColumn((prev) =>
          dataset.columns.some((c) => c.name === prev) ? prev : (dataset.columns[0]?.name ?? ""),
        );
      })
      .catch((err: unknown) => {
        if (active) setFailure(err instanceof Error ? err.message : "Could not load the dataset");
      });
    return () => {
      active = false;
    };
  }, [datasetId]);

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      const experiment = await createExperiment({
        name: name.trim(),
        objective: objective.trim(),
        dataset_id: datasetId,
        target_column: targetColumn,
        task_type: taskType,
      });
      setOpen(false);
      onCreated(experiment);
    } catch (err) {
      // Verbatim — a 409 here means the name is taken, and the reader needs to
      // know that rather than see a form that appeared to do nothing.
      setFailure(err instanceof Error ? err.message : "Could not create the experiment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setFailure(null);
        setOpen(next);
      }}
      title="New experiment"
      trigger={<Button size="sm">New experiment</Button>}
    >
      <div className={styles.form}>
        <label className={styles.field}>
          <span className={styles.label}>Name</span>
          <Input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Objective</span>
          <Textarea
            aria-label="Objective"
            rows={2}
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Dataset</span>
          <select
            aria-label="Dataset"
            className={styles.select}
            value={datasetId}
            onChange={(e) => setDatasetId(e.target.value)}
          >
            {(datasets ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Target column</span>
          <select
            aria-label="Target column"
            className={styles.select}
            value={targetColumn}
            onChange={(e) => setTargetColumn(e.target.value)}
          >
            {columns.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>
            Task type <span className={styles.hint}>fixes the metric runs are ranked on</span>
          </span>
          <select
            aria-label="Task type"
            className={styles.select}
            value={taskType}
            onChange={(e) => setTaskType(e.target.value)}
          >
            <option value="regression">regression</option>
            <option value="classification">classification</option>
          </select>
        </label>

        {failure && <ErrorBanner message={failure} />}

        <div className={styles.actions}>
          <p className={styles.hint}>Names are unique across investigations.</p>
          <Button size="sm" loading={busy} disabled={!name.trim()} onClick={() => void submit()}>
            Create
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
