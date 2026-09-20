import { useEffect, useMemo, useState } from "react";
import { getDataset, listModels, trainRun, tuneRun } from "../api";
import type { DatasetColumn, ExperimentRow, ModelSpec } from "../types";
import ErrorBanner from "./ErrorBanner";
import { Button, Dialog, Input, Textarea } from "../ui";
import styles from "./DialogForm.module.css";

interface NewRunDialogProps {
  experiment: ExperimentRow;
  /** Called after a run (or a whole search) lands, so the caller can refetch
   *  the leaderboard the new rows belong on. */
  onCreated: () => void;
}

type Mode = "train" | "tune";

/** Launch a run inside one investigation (#52). Every choice on this form is
 *  read from the backend — the model list from `GET /models`, the columns from
 *  `GET /datasets/{id}` — so it cannot drift from `MODEL_REGISTRY` or from the
 *  dataset the way a hand-maintained list did (#51). `dataset_id`,
 *  `target_column` and `task_type` are the experiment's and are not asked for:
 *  a run cannot disagree with the investigation it belongs to (D34).
 */
export default function NewRunDialog({ experiment, onCreated }: NewRunDialogProps) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<ModelSpec[] | null>(null);
  const [columns, setColumns] = useState<DatasetColumn[]>([]);
  const [modelType, setModelType] = useState("");
  const [mode, setMode] = useState<Mode>("train");
  const [hyperparams, setHyperparams] = useState<Record<string, string>>({});
  const [nTrials, setNTrials] = useState("20");
  const [timeColumn, setTimeColumn] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  // Loaded on first open rather than on mount: the leaderboard is what the page
  // is for, and most visits never launch anything.
  useEffect(() => {
    if (!open || models !== null) return;
    let active = true;
    Promise.all([listModels(), experiment.dataset_id ? getDataset(experiment.dataset_id) : null])
      .then(([specs, dataset]) => {
        if (!active) return;
        setModels(specs);
        setColumns(dataset?.columns ?? []);
      })
      .catch((err: unknown) => {
        if (active) setFailure(err instanceof Error ? err.message : "Could not load the form");
      });
    return () => {
      active = false;
    };
  }, [open, models, experiment.dataset_id]);

  // A classifier cannot be scored on a regression's metric; the backend 422s on
  // the mismatch, so it is not worth offering.
  const usable = useMemo(
    () => (models ?? []).filter((m) => m.task_type === experiment.task_type),
    [models, experiment.task_type],
  );

  const spec = usable.find((m) => m.model_type === modelType) ?? usable[0] ?? null;

  /** The target is the answer, never an input — offering it as a feature or as
   *  the split axis is a leak the metrics would not reveal. */
  const choosable = useMemo(
    () => columns.filter((c) => c.name !== experiment.target_column),
    [columns, experiment.target_column],
  );

  // Falling back to Train keeps the form honest when the chosen model has an
  // empty search space: the Tune radio is disabled, and a stale `mode` would
  // otherwise submit a request the backend rejects.
  const effectiveMode: Mode = spec && !spec.tunable ? "train" : mode;
  /** Column hyperparameters with no choice made. Tune does not send them — the
   *  search has nothing to vary — so they only gate the train path. */
  const missingColumns = useMemo(
    () =>
      effectiveMode === "train" && spec
        ? spec.column_hyperparams.filter((name) => !(hyperparams[name] ?? "").trim())
        : [],
    [effectiveMode, spec, hyperparams],
  );

  function setHyperparam(name: string, value: string) {
    setHyperparams((prev) => ({ ...prev, [name]: value }));
  }

  async function submit() {
    if (!spec) return;
    setBusy(true);
    setFailure(null);
    try {
      if (effectiveMode === "tune") {
        await tuneRun(experiment.id, {
          model_type: spec.model_type,
          n_trials: Number(nTrials),
          ...(timeColumn ? { time_column: timeColumn } : {}),
          notes,
        });
      } else {
        // Numeric boxes send numbers; column pickers send the column name. An
        // empty box is omitted so the estimator keeps its own default.
        const values: Record<string, number | string> = {};
        for (const h of spec.hyperparams) {
          const raw = hyperparams[h.name];
          if (raw !== undefined && raw !== "") values[h.name] = Number(raw);
        }
        // No fallback: a column hyperparameter names a MEANING, not a slot.
        // `prior_column` is the lagged target the persistence baseline repeats,
        // and the first column of the frame is only that by coincidence. A
        // wrong one still fits, still logs, and still anchors the leaderboard
        // every other run is judged against. `missingColumns` blocks submit, so
        // this loop can assume a real choice.
        for (const name of spec.column_hyperparams) {
          values[name] = hyperparams[name] as string;
        }
        await trainRun(experiment.id, {
          model_type: spec.model_type,
          hyperparams: values,
          ...(timeColumn ? { time_column: timeColumn } : {}),
          notes,
        });
      }
      setOpen(false);
      onCreated();
    } catch (err) {
      // Verbatim: the backend names the offending column or metric, and a
      // generic message would leave the form unfixable.
      setFailure(err instanceof Error ? err.message : "Could not launch the run");
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
      title={`New run — ${experiment.name}`}
      trigger={<Button size="sm">New run</Button>}
    >
      <div className={styles.form}>
        <label className={styles.field}>
          <span className={styles.label}>Model</span>
          <select
            aria-label="Model"
            className={styles.select}
            value={spec?.model_type ?? ""}
            onChange={(e) => setModelType(e.target.value)}
          >
            {usable.map((m) => (
              <option key={m.model_type} value={m.model_type}>
                {m.model_type}
              </option>
            ))}
          </select>
        </label>

        <fieldset className={styles.modes}>
          <legend className={styles.label}>Mode</legend>
          <label className={styles.radio}>
            <input
              type="radio"
              name="mode"
              aria-label="Train"
              checked={effectiveMode === "train"}
              onChange={() => setMode("train")}
            />
            Train
          </label>
          <label className={styles.radio}>
            <input
              type="radio"
              name="mode"
              aria-label="Tune"
              checked={effectiveMode === "tune"}
              // An empty search space means /tune 422s on this model (D25).
              disabled={!spec?.tunable}
              onChange={() => setMode("tune")}
            />
            Tune
          </label>
        </fieldset>

        {effectiveMode === "tune" ? (
          <label className={styles.field}>
            <span className={styles.label}>Trials</span>
            <Input
              type="number"
              aria-label="Trials"
              min={1}
              value={nTrials}
              onChange={(e) => setNTrials(e.target.value)}
            />
          </label>
        ) : (
          <>
            {spec?.hyperparams.map((h) => (
              <label key={h.name} className={styles.field}>
                <span className={styles.label}>
                  {h.name} <span className={styles.hint}>{`${h.min} – ${h.max}`}</span>
                </span>
                <Input
                  type="number"
                  aria-label={h.name}
                  step="any"
                  value={hyperparams[h.name] ?? ""}
                  onChange={(e) => setHyperparam(h.name, e.target.value)}
                />
              </label>
            ))}
            {spec?.column_hyperparams.map((name) => (
              <label key={name} className={styles.field}>
                <span className={styles.label}>{name}</span>
                <select
                  aria-label={name}
                  className={styles.select}
                  value={hyperparams[name] ?? ""}
                  onChange={(e) => setHyperparam(name, e.target.value)}
                >
                  {/* Without this the browser displays the first column as
                      though it had been chosen, while the state behind it is
                      still empty — the form looks answered and is not. */}
                  <option value="">Select a column…</option>
                  {choosable.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </>
        )}

        <label className={styles.field}>
          <span className={styles.label}>
            Time column <span className={styles.hint}>splits chronologically</span>
          </span>
          <select
            aria-label="Time column"
            className={styles.select}
            value={timeColumn}
            onChange={(e) => setTimeColumn(e.target.value)}
          >
            <option value="">None — random split</option>
            {choosable.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Notes</span>
          <Textarea aria-label="Notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>

        {failure && <ErrorBanner message={failure} />}

        {missingColumns.length > 0 && (
          <p className={styles.hint}>
            {`Choose a value for ${missingColumns.join(", ")} before launching.`}
          </p>
        )}

        <div className={styles.actions}>
          {/* Training and tuning run synchronously inside the request (D17):
              a search of 20 trials can hold this dialog open for minutes. */}
          <p className={styles.hint}>
            {effectiveMode === "tune"
              ? "The search runs now — this can take several minutes."
              : "The run happens now — this can take a moment."}
          </p>
          <Button
            size="sm"
            loading={busy}
            disabled={!spec || missingColumns.length > 0}
            onClick={() => void submit()}
          >
            Launch
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
