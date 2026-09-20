import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { createChat, getDataset, runEda } from "../api";
import type { DatasetDetail } from "../types";
import AppShell from "../components/AppShell";
import ErrorBanner from "../components/ErrorBanner";
import FindingsPanel from "../components/FindingsPanel";
import { Button, Skeleton } from "../ui";
import styles from "./DatasetPage.module.css";

/**
 * One dataset: its shape, its columns, and its EDA write-ups.
 *
 * Before this, running EDA and reading the result happened in different
 * sections — the button lived in the dataset sidebar and the draft it produced
 * could only be found in the `/review` queue. Both now sit on the page for the
 * dataset they are about, which is also what makes the rail's dataset entries
 * worth clicking.
 */
export default function DatasetPage() {
  const { datasetId } = useParams<{ datasetId: string }>();
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  /** Bumped after an EDA pass so the panel below refetches and the new draft
   *  appears in place — the run and its output stay on one screen. */
  const [findingsKey, setFindingsKey] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    if (!datasetId) return;
    let active = true;
    setDataset(null);
    setError(null);
    getDataset(datasetId)
      .then((d) => active && setDataset(d))
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load dataset");
      });
    return () => {
      active = false;
    };
  }, [datasetId]);

  async function startEda() {
    if (!datasetId || running) return;
    setRunning(true);
    setError(null);
    try {
      // Synchronous inside the request by design (D23) — the judge-gated loop
      // runs several passes, so this takes tens of seconds.
      await runEda(datasetId);
      setFindingsKey((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not run EDA");
    } finally {
      setRunning(false);
    }
  }

  async function startChat() {
    if (!datasetId || starting) return;
    setStarting(true);
    try {
      const chat = await createChat([datasetId]);
      navigate(`/c/${chat.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start chat");
      setStarting(false);
    }
  }

  return (
    <AppShell width="wide">
      <div className={styles.page}>
        {error && <ErrorBanner message={error} />}
        {dataset === null && !error && <Skeleton count={5} />}

        {dataset !== null && (
          <>
            <header className={styles.header}>
              <div>
                <h1 className={styles.title}>{dataset.name}</h1>
                <p className={styles.meta}>
                  {dataset.n_rows.toLocaleString()} rows × {dataset.n_cols} columns
                </p>
              </div>
              <div className={styles.headerActions}>
                <Button variant="ghost" loading={starting} onClick={() => void startChat()}>
                  Start chat
                </Button>
                <Button loading={running} onClick={() => void startEda()}>
                  {running ? "Running EDA…" : "Run EDA"}
                </Button>
              </div>
            </header>

            <section aria-label="Columns">
              <h2 className={styles.sectionTitle}>Columns</h2>
              {/* Scrolls inside its own box rather than widening the page — a
                  dataset can carry far more columns than fit at any width. */}
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">Type</th>
                      <th scope="col">Nulls</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dataset.columns.map((c) => (
                      <tr key={c.name}>
                        <td>{c.name}</td>
                        <td className={styles.muted}>{c.inferred_type}</td>
                        <td className={styles.num}>{c.null_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <FindingsPanel
              sourceType="eda"
              sourceId={dataset.id}
              refreshKey={findingsKey}
              title="EDA findings"
              empty="No EDA write-ups yet — run one above."
            />
          </>
        )}
      </div>
    </AppShell>
  );
}
