import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { createChat, listDatasets, listExperiments } from "../api";
import type { DatasetOut, ExperimentRow } from "../types";
import { Button, Skeleton } from "../ui";
import styles from "./NavRail.module.css";

const GROUPS_KEY = "wp-rail-collapsed";

/**
 * The one navigation surface: categories, then the entities under them.
 *
 * This replaces a split that had no principle behind it — a horizontal row of
 * section links in the topbar, plus a left sidebar that listed datasets no
 * matter which section you were in, so the experiments pages carried a dataset
 * nav they had no use for. Here both kinds of entity sit under the category
 * that owns them, and what you can click is always what you can see.
 *
 * Datasets keep their checkboxes: a chat can span N datasets (#6) and they are
 * fixed at creation, so multi-select has to live wherever datasets are listed.
 * A bare row click opens the dataset's page rather than starting a chat — the
 * page carries Start chat and Run EDA, and it is where an EDA draft lands, so
 * generating a write-up and reading it no longer happen in different sections.
 */
export default function NavRail() {
  const [datasets, setDatasets] = useState<DatasetOut[] | null>(null);
  const [experiments, setExperiments] = useState<ExperimentRow[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(initialCollapsed);
  const navigate = useNavigate();

  useEffect(() => {
    let active = true;
    listDatasets()
      .then((ds) => active && setDatasets(ds))
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load datasets");
      });
    // Independent of the datasets call: one section failing should not blank
    // the other, since each is a separate list the reader may be heading for.
    listExperiments()
      .then((xs) => active && setExperiments(xs))
      .catch(() => active && setExperiments([]));
    return () => {
      active = false;
    };
  }, []);

  function toggleGroup(key: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      try {
        localStorage.setItem(GROUPS_KEY, [...next].join(","));
      } catch {
        // ignore persistence failures (private mode, etc.)
      }
      return next;
    });
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  async function startChat(ids: string[]) {
    if (ids.length === 0 || starting) return;
    setStarting(true);
    try {
      const chat = await createChat(ids);
      navigate(`/c/${chat.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start chat");
    } finally {
      setStarting(false);
    }
  }

  const dataOpen = !collapsed.has("data");
  const mlOpen = !collapsed.has("ml");
  // A third top-level category, not a child of Machine learning: the agent
  // reads across both halves, dataset EDA findings included.
  const agentOpen = !collapsed.has("agent");

  return (
    <nav aria-label="Sections" className={styles.rail}>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <div className={styles.group}>
        <h2 className={styles.category}>Data</h2>
        <NavLink to="/" className={styles.action}>
          + New upload
        </NavLink>

        <button
          type="button"
          className={styles.groupToggle}
          aria-expanded={dataOpen}
          onClick={() => toggleGroup("data")}
        >
          <span className={styles.chevron} data-open={dataOpen} aria-hidden="true" />
          <span className={styles.groupName}>Datasets</span>
          <span className={styles.count}>{datasets?.length ?? ""}</span>
        </button>

        {dataOpen && (
          <ul className={styles.items}>
            {datasets === null && !error && (
              <li className={styles.loading}>
                <Skeleton count={3} />
              </li>
            )}
            {datasets?.length === 0 && (
              <li className={styles.empty}>
                No datasets yet — <NavLink to="/">upload one</NavLink>.
              </li>
            )}
            {datasets?.map((d) => (
              <li key={d.id} className={styles.item} data-selected={selected.has(d.id)}>
                <input
                  type="checkbox"
                  className={styles.check}
                  checked={selected.has(d.id)}
                  onChange={() => toggleSelect(d.id)}
                  aria-label={`Select ${d.name}`}
                />
                <NavLink to={`/datasets/${d.id}`} className={styles.entity} title={d.name}>
                  <span className={styles.entityName}>{d.name}</span>
                  <span className={styles.entityMeta}>
                    {d.n_rows} × {d.n_cols}
                  </span>
                </NavLink>
              </li>
            ))}
          </ul>
        )}

        {selected.size > 0 && (
          <div className={styles.footer}>
            <Button size="sm" loading={starting} onClick={() => void startChat([...selected])}>
              Start chat with {selected.size} dataset
              {selected.size === 1 ? "" : "s"}
            </Button>
          </div>
        )}
      </div>

      <div className={styles.group}>
        <h2 className={styles.category}>Machine learning</h2>

        <button
          type="button"
          className={styles.groupToggle}
          aria-expanded={mlOpen}
          onClick={() => toggleGroup("ml")}
        >
          <span className={styles.chevron} data-open={mlOpen} aria-hidden="true" />
          <span className={styles.groupName}>Experiments</span>
          <span className={styles.count}>{experiments?.length ?? ""}</span>
        </button>

        {mlOpen && (
          <ul className={styles.items}>
            <li className={styles.item}>
              <NavLink to="/experiments" end className={styles.entity}>
                <span className={styles.entityName}>All experiments</span>
              </NavLink>
            </li>
            {experiments === null && (
              <li className={styles.loading}>
                <Skeleton count={2} />
              </li>
            )}
            {experiments?.map((x) => (
              <li key={x.id} className={styles.item}>
                <NavLink to={`/experiments/${x.id}`} className={styles.entity} title={x.name}>
                  <span className={styles.entityName}>{x.name}</span>
                  <span className={styles.entityMeta}>
                    {x.n_runs} run{x.n_runs === 1 ? "" : "s"}
                  </span>
                </NavLink>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={styles.group}>
        <h2 className={styles.category}>Agent</h2>

        <button
          type="button"
          className={styles.groupToggle}
          aria-expanded={agentOpen}
          onClick={() => toggleGroup("agent")}
        >
          <span className={styles.chevron} data-open={agentOpen} aria-hidden="true" />
          {/* Not "Ask": the chat page's submit button already answers to
              that exact accessible name, and two buttons sharing one make
              every getByRole query for it ambiguous. */}
          <span className={styles.groupName}>Ask history</span>
        </button>

        {agentOpen && (
          <ul className={styles.items}>
            <li className={styles.item}>
              <NavLink to="/ask" end className={styles.entity}>
                <span className={styles.entityName}>Ask about history</span>
              </NavLink>
            </li>
          </ul>
        )}
      </div>
    </nav>
  );
}

function initialCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(GROUPS_KEY);
    return new Set(raw ? raw.split(",").filter(Boolean) : []);
  } catch {
    return new Set();
  }
}
