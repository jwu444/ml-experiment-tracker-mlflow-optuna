import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { getExperiment, getLeaderboard, runDiagnostics, updateRun } from "../api";
import type { ExperimentRow, Leaderboard, NotesStatus, RunRow } from "../types";
import AppShell from "../components/AppShell";
import ErrorBanner from "../components/ErrorBanner";
import NewRunDialog from "../components/NewRunDialog";
import FindingsPanel from "../components/FindingsPanel";
import { Badge, Button, Dialog, Skeleton, Textarea } from "../ui";
import styles from "./ExperimentDetailPage.module.css";

function formatMetric(value: number): string {
  // Enough precision to separate two close runs, without printing float noise.
  return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/\.?0+$/, "");
}

/** Every key present in any of the given records, in first-seen order. */
function unionKeys(records: Record<string, unknown>[]): string[] {
  const keys: string[] = [];
  for (const record of records) {
    for (const key of Object.keys(record)) if (!keys.includes(key)) keys.push(key);
  }
  return keys;
}

export default function ExperimentDetailPage() {
  const { experimentId } = useParams<{ experimentId: string }>();
  const [experiment, setExperiment] = useState<ExperimentRow | null>(null);
  const [leaderboard, setLeaderboard] = useState<Leaderboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [reviewing, setReviewing] = useState<string | null>(null);
  // Per-run, not page-global: a diagnostics pass runs the judge-gated loop and
  // takes tens of seconds, and freezing the whole leaderboard meanwhile reads
  // as a hung page.
  const [diagnosing, setDiagnosing] = useState<Set<string>>(new Set());
  /** The run whose diagnostic write-ups are open below the leaderboard — set by
   *  a completed pass, and by the Diagnostics button on any run that already has
   *  one. A run id, not a message: the panel it drives has to know WHICH run. */
  const [diagnostic, setDiagnostic] = useState<string | null>(null);
  /** Bumped after a pass so the open panel refetches and the new draft appears. */
  const [findingsKey, setFindingsKey] = useState(0);
  // "" is "all models". Client-side over the already-ranked rows: the
  // leaderboard route ranks a whole investigation in one call (D38), so
  // re-fetching per filter would buy nothing and cost a round trip.
  const [modelFilter, setModelFilter] = useState("");

  useEffect(() => {
    if (!experimentId) return;
    let active = true;
    setExperiment(null);
    setLeaderboard(null);
    setError(null);
    setModelFilter("");
    Promise.all([getExperiment(experimentId), getLeaderboard(experimentId)])
      .then(([exp, board]) => {
        if (!active) return;
        setExperiment(exp);
        setLeaderboard(board);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load experiment");
      });
    return () => {
      active = false;
    };
  }, [experimentId]);

  const rows = leaderboard?.rows ?? null;
  // A row with no mlflow read means params/metrics on every row are missing,
  // not wrong — the leaderboard route answers with our own records either way.
  const degraded = leaderboard !== null && !leaderboard.mlflow_available;

  const chosen = useMemo(
    () => (rows ?? []).filter((r) => selected.has(r.run.id)).map((r) => r.run),
    [rows, selected],
  );

  // Derived from the runs actually on this leaderboard, never from a
  // hand-maintained list: the previous filter hardcoded its options and so
  // silently hid every `persistence` run once that model joined
  // MODEL_REGISTRY (#51). A list built from the data cannot drift from it.
  const modelTypes = useMemo(
    () => [...new Set((rows ?? []).map((r) => r.run.model_type))].sort(),
    [rows],
  );

  // Ranks are the backend's (D38) and are shown unchanged — renumbering a
  // filtered view would announce the surviving row as rank 1 when it is not.
  const visibleRows = useMemo(
    () => (rows ?? []).filter((r) => modelFilter === "" || r.run.model_type === modelFilter),
    [rows, modelFilter],
  );

  /** Narrowing the view drops the comparison too: a row selected and then
   *  filtered out is a checkbox the user can no longer reach to uncheck,
   *  silently feeding a hidden run into the compare table. */
  function selectModel(next: string) {
    if (next === modelFilter) return;
    setSelected(new Set());
    setModelFilter(next);
  }

  /** Refetch after a run lands. Deliberately does not blank the board first —
   *  a launch adds rows, and clearing to a skeleton would read as a page that
   *  threw away what it was showing. `n_runs` on the header moved too, hence
   *  refetching the experiment and not only the leaderboard.
   *
   *  The model filter is dropped, because it was chosen to narrow a board the
   *  new run was not on. Left in place it can hide the very row the launch just
   *  produced: the header count goes up, the table does not change, and nothing
   *  reports an error. */
  async function reload() {
    if (!experimentId) return;
    selectModel("");
    try {
      const [exp, board] = await Promise.all([
        getExperiment(experimentId),
        getLeaderboard(experimentId),
      ]);
      setExperiment(exp);
      setLeaderboard(board);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reload experiment");
    }
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /** Kick off a diagnostics pass. Returns 201 with a DRAFT finding (D23).
   *  The draft used to be announced and then left in a separate queue; it now
   *  opens below the leaderboard, so the run, the pass, and the write-up it
   *  produced are all on one screen. */
  async function startDiagnostics(run: RunRow) {
    if (diagnosing.has(run.id)) return;
    setDiagnosing((prev) => new Set(prev).add(run.id));
    setDiagnostic(null);
    setError(null);
    try {
      await runDiagnostics(run.id);
      setDiagnostic(run.id);
      setFindingsKey((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not run diagnostics");
    } finally {
      setDiagnosing((prev) => {
        const next = new Set(prev);
        next.delete(run.id);
        return next;
      });
    }
  }

  /** Merge a PATCH response back into the leaderboard rows in place, so the
   *  badge updates without a refetch throwing away the current selection. */
  function replaceRun(updated: RunRow) {
    setLeaderboard((prev) =>
      prev
        ? { ...prev, rows: prev.rows.map((r) => (r.run.id === updated.id ? { ...r, run: updated } : r)) }
        : prev,
    );
  }

  return (
    // The leaderboard carries a checkbox, rank, model, holdout metric, cv ± std,
    // notes and actions. At the `chat` default those clipped rather than merely
    // crowded — the notes column in particular was ellipsed to nothing.
    <AppShell width="wide">
      <div className={styles.page}>
          {experiment === null && !error && <Skeleton count={4} />}
          {experiment !== null && (
            <header className={styles.header}>
              <h1 className={styles.title}>{experiment.name}</h1>
              <p className={styles.objective}>{experiment.objective}</p>
              <div className={styles.meta}>
                <span>{experiment.task_type}</span>
                <span>
                  {experiment.primary_metric} ({experiment.metric_direction})
                </span>
                <span>{experiment.n_runs} runs</span>
              </div>
            </header>
          )}

          {error && <ErrorBanner message={error} />}
          {degraded && (
            <p role="status" className={styles.warning}>
              The MLflow tracking store is unavailable — runs are listed unranked, newest first,
              until it is reachable again.
            </p>
          )}

          {experiment && (
            <div className={styles.filters}>
              {/* The filter is conditional on there being runs to filter; the
                  launcher is not — an investigation with no runs yet is
                  exactly the one that needs it most. */}
              {modelTypes.length > 0 && (
                <select
                  aria-label="Model type"
                  className={styles.select}
                  value={modelFilter}
                  onChange={(e) => selectModel(e.target.value)}
                >
                  <option value="">All models</option>
                  {modelTypes.map((modelType) => (
                    <option key={modelType} value={modelType}>
                      {modelType}
                    </option>
                  ))}
                </select>
              )}
              <NewRunDialog experiment={experiment} onCreated={() => void reload()} />
            </div>
          )}

          {rows !== null && (
            <div className={styles.tableScroll}>
              <table aria-label="Leaderboard" className={styles.leaderboard}>
                <thead>
                  <tr>
                    <th scope="col" aria-label="Compare" />
                    <th scope="col">Rank</th>
                    <th scope="col">Model</th>
                    <th scope="col">{leaderboard?.primary_metric}</th>
                    <th scope="col">{`cv_${leaderboard?.primary_metric ?? ""} ± cv_std`}</th>
                    <th scope="col">Status</th>
                    <th scope="col">Notes</th>
                    <th scope="col" aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => (
                    <tr key={row.run.id} data-best={row.is_best ? "true" : undefined}>
                      <td>
                        <input
                          type="checkbox"
                          className={styles.check}
                          checked={selected.has(row.run.id)}
                          onChange={() => toggle(row.run.id)}
                          aria-label={`Select ${row.run.id} for comparison`}
                        />
                      </td>
                      <td>{row.rank === null ? "—" : row.rank}</td>
                      <td>
                        {row.run.model_type}
                        <span className={styles.runId}> {row.run.id}</span>
                        {row.is_best && (
                          <>
                            {" "}
                            <Badge tone="accent">Best</Badge>
                            {row.within_noise && (
                              <span className={styles.withinNoise}> within noise</span>
                            )}
                          </>
                        )}
                      </td>
                      <td>{row.value === null ? "—" : formatMetric(row.value)}</td>
                      <td>
                        {row.cv_value === null
                          ? "—"
                          : row.cv_std === null
                            ? formatMetric(row.cv_value)
                            : `${formatMetric(row.cv_value)} ± ${formatMetric(row.cv_std)}`}
                      </td>
                      <td>
                        {row.run.status && (
                          <Badge tone={row.run.status === "FINISHED" ? "neutral" : "danger"}>
                            {row.run.status}
                          </Badge>
                        )}
                      </td>
                      <td className={styles.notes}>{row.run.notes || <em>no notes yet</em>}</td>
                      <td className={styles.actions}>
                        <ReviewDialog
                          run={row.run}
                          open={reviewing === row.run.id}
                          onOpenChange={(open) => setReviewing(open ? row.run.id : null)}
                          onUpdated={replaceRun}
                          degraded={degraded}
                        />
                        {/* Residuals are undefined for a classifier and the route
                            409s on one, so do not offer a click that cannot succeed. */}
                        <Button
                          size="sm"
                          variant="ghost"
                          loading={diagnosing.has(row.run.id)}
                          disabled={row.run.task_type !== "regression"}
                          title={
                            row.run.task_type === "regression"
                              ? undefined
                              : "Diagnostics are regression-only — residuals are undefined for a classifier."
                          }
                          aria-label={`Run diagnostics for ${row.run.id}`}
                          onClick={() => void startDiagnostics(row.run)}
                        >
                          {diagnosing.has(row.run.id) ? "Running…" : "Diagnostics"}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {chosen.length >= 2 && (
            <CompareTable
              runs={chosen}
              degraded={degraded}
              primaryMetric={experiment?.primary_metric ?? ""}
              metricDirection={experiment?.metric_direction ?? "minimize"}
            />
          )}

        {/* Keyed by run id so switching runs remounts rather than showing the
            previous run's write-ups under the new run's heading. */}
        {diagnostic && (
          <FindingsPanel
            key={diagnostic}
            sourceType="diagnostic"
            sourceId={diagnostic}
            refreshKey={findingsKey}
            title={`Diagnostics — run ${diagnostic.slice(0, 8)}`}
            empty="No diagnostic write-ups for this run yet."
          />
        )}
      </div>
    </AppShell>
  );
}

interface ReviewDialogProps {
  run: RunRow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (run: RunRow) => void;
  degraded: boolean;
}

function ReviewDialog({ run, open, onOpenChange, onUpdated, degraded }: ReviewDialogProps) {
  const [notes, setNotes] = useState(run.notes);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function submit(patch: { notes?: string; notes_status?: NotesStatus }) {
    setBusy(true);
    setFailure(null);
    try {
      onUpdated(await updateRun(run.id, patch));
      onOpenChange(false);
    } catch (err) {
      setFailure(err instanceof Error ? err.message : "Could not save the note");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setNotes(run.notes); // reopen shows what is stored, not a stale edit
        onOpenChange(next);
      }}
      title={`Review notes — ${run.model_type}`}
      trigger={
        <Button size="sm" variant="ghost" aria-label={`Review notes for ${run.id}`}>
          Review notes
        </Button>
      }
    >
      {!degraded && (
        <dl className={styles.detail}>
          {Object.entries(run.params).map(([name, value]) => (
            <div key={`p-${name}`} className={styles.detailPair}>
              <dt>{name}</dt>
              <dd>{value}</dd>
            </div>
          ))}
          {Object.entries(run.metrics).map(([name, value]) => (
            <div key={`m-${name}`} className={styles.detailPair}>
              <dt>{name}</dt>
              <dd>{formatMetric(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      <Textarea
        aria-label="Notes"
        rows={5}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />
      {failure && <ErrorBanner message={failure} />}
      <div className={styles.actions}>
        {/* Save writes text and nothing else. Approval is a separate button
            because a write that approved itself would let the seeding script
            bless every note it generated (D20). */}
        <Button size="sm" variant="ghost" loading={busy} onClick={() => void submit({ notes })}>
          Save
        </Button>
        {/* The backend 422s on approving an empty note, so do not offer it. */}
        <Button
          size="sm"
          loading={busy}
          disabled={!notes.trim()}
          onClick={() => void submit({ notes, notes_status: "approved" })}
        >
          Approve
        </Button>
        <Button
          size="sm"
          variant="ghost"
          loading={busy}
          // Sends `notes` for the same reason Save and Approve do: whatever is
          // in the textarea is the reviewer's work, and a reject often *is*
          // the note ("target leaks, ignore this run"). The backend has no
          // empty-note guard on rejection.
          onClick={() => void submit({ notes, notes_status: "rejected" })}
        >
          Reject
        </Button>
      </div>
    </Dialog>
  );
}

interface CompareTableProps {
  runs: RunRow[];
  degraded: boolean;
  primaryMetric: string;
  metricDirection: string;
}

/** Multi-select comparison across runs within one experiment. Unlike the old
 *  page-level CompareTable this never guards against mixed task types — D34
 *  makes that unrepresentable inside a single experiment, since task_type now
 *  lives on the parent and every run here shares it. Adds a per-metric winner
 *  marker for the experiment's own primary metric (the only one whose
 *  direction — minimize/maximize — is known); other metrics are shown without
 *  a marker rather than guessing a direction for them. */
function CompareTable({ runs, degraded, primaryMetric, metricDirection }: CompareTableProps) {
  const metricNames = degraded ? [] : unionKeys(runs.map((run) => run.metrics));
  const paramNames = degraded ? [] : unionKeys(runs.map((run) => run.params));

  function winnerId(name: string): string | null {
    if (name !== primaryMetric) return null;
    const values = runs
      .map((run) => ({ id: run.id, value: run.metrics[name] }))
      .filter((v): v is { id: string; value: number } => v.value !== undefined);
    if (values.length < 2) return null;
    const best =
      metricDirection === "maximize"
        ? Math.max(...values.map((v) => v.value))
        : Math.min(...values.map((v) => v.value));
    return values.find((v) => v.value === best)?.id ?? null;
  }

  return (
    <div className={styles.tableScroll}>
      <table aria-label="Compare selected runs" className={styles.compare}>
        <thead>
          <tr>
            <th scope="col">Field</th>
            {runs.map((run) => (
              <th key={run.id} scope="col">
                {run.model_type}
                <span className={styles.runId}> {run.id}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metricNames.map((name) => {
            const winner = winnerId(name);
            return (
              <tr key={`m-${name}`}>
                <th scope="row">{name}</th>
                {runs.map((run) => (
                  <td key={run.id} data-winner={run.id === winner ? "true" : undefined}>
                    {run.metrics[name] === undefined ? "—" : formatMetric(run.metrics[name])}
                    {run.id === winner && <span className={styles.winner}> best</span>}
                  </td>
                ))}
              </tr>
            );
          })}
          {paramNames.map((name) => (
            <tr key={`p-${name}`}>
              <th scope="row">{name}</th>
              {runs.map((run) => (
                <td key={run.id}>{run.params[name] ?? "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
