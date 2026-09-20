import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listExperiments } from "../api";
import type { ExperimentRow } from "../types";
import AppShell from "../components/AppShell";
import ErrorBanner from "../components/ErrorBanner";
import NewExperimentDialog from "../components/NewExperimentDialog";
import { Skeleton } from "../ui";
import styles from "./ExperimentsPage.module.css";

export default function ExperimentsPage() {
  const [rows, setRows] = useState<ExperimentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setRows(null);
    setError(null);
    listExperiments()
      .then((data) => {
        if (active) setRows(data);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load experiments");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    // Five columns, one of them free-form objective prose and one a locale
    // timestamp. At the `chat` default (820px) they squeezed each other into
    // unreadable slivers; this table needs the room.
    <AppShell width="wide">
      <div className={styles.page}>
        <header className={styles.header}>
          <h1 className={styles.title}>Experiments</h1>
          {/* Prepended, not refetched: the list is newest-first and the row we
              were just handed is by definition the newest. */}
          <NewExperimentDialog onCreated={(row) => setRows((prev) => [row, ...(prev ?? [])])} />
        </header>

        {error && <ErrorBanner message={error} />}
        {rows === null && !error && <Skeleton count={4} />}
        {rows !== null && rows.length === 0 && (
          <p className={styles.empty}>
            No experiments yet. Create one through <code>POST /experiments</code>.
          </p>
        )}

        {rows !== null && rows.length > 0 && (
          <div className={styles.tableScroll}>
            <table aria-label="Investigations" className={styles.list}>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Objective</th>
                  <th scope="col">Dataset</th>
                  <th scope="col">Runs</th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td className={styles.name}>
                      <Link to={`/experiments/${row.id}`}>{row.name}</Link>
                    </td>
                    <td className={styles.objective}>
                      {row.objective || <em>no objective set</em>}
                    </td>
                    {/* The name, not the id — a uuid in this column tells the
                        reader nothing about which data the investigation is over.
                        Falls back to the id if a dataset row has gone missing, so
                        the cell still identifies something. */}
                    <td className={styles.dataset}>
                      {row.dataset_name ?? row.dataset_id ?? <em>none</em>}
                    </td>
                    <td className={styles.count}>{row.n_runs}</td>
                    <td className={styles.created}>{new Date(row.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
