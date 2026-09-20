import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { type Finding, listFindings, updateFinding } from "../api";
import ErrorBanner from "./ErrorBanner";
import { Badge, Button, Textarea } from "../ui";
import styles from "./FindingsPanel.module.css";

interface FindingsPanelProps {
  /** Which table `sourceId` addresses (D22). `eda` → a dataset, `diagnostic` → a run. */
  sourceType: "eda" | "diagnostic";
  sourceId: string;
  /** Heading for the panel. */
  title: string;
  /** Shown when the source has no findings at all. */
  empty: string;
  /** Bump to refetch — a generation endpoint that just created a draft passes
   *  an incremented value so the new row appears without a page reload. */
  refreshKey?: number;
}

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  approved: "Approved",
  rejected: "Rejected",
};

/**
 * One source's findings, reviewable in place.
 *
 * This replaces the standalone `/review` queue. D26 gated bulk approval on
 * having expanded a row, because that page approved N rows at once and the text
 * of most of them was off screen. Here every finding's text is rendered
 * unclamped next to its own Approve button, so the property D26 was buying —
 * approval only of text that was actually rendered — holds by construction
 * rather than by a tracked `read` set. Phase 4 still gets what it needs from
 * `status`, and it gets it from a reviewer who was looking at the write-up.
 *
 * Read mode renders the Markdown these write-ups are written in; Edit swaps in a
 * textarea over the RAW source, never over anything derived from the rendered
 * output — saving rendered text would silently strip the formatting (#49).
 */
export default function FindingsPanel({
  sourceType,
  sourceId,
  title,
  empty,
  refreshKey = 0,
}: FindingsPanelProps) {
  const [rows, setRows] = useState<Finding[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Set<string>>(new Set());
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setError(null);
    try {
      // Narrowed server-side. Fetching broadly and filtering here would drop
      // everything past the route's limit and render as "no findings yet".
      setRows(await listFindings({ source_type: sourceType, source_id: sourceId }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load findings");
    }
  }, [sourceType, sourceId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  function currentText(row: Finding): string {
    return edits[row.id] ?? row.text;
  }

  function toggleEdit(row: Finding) {
    setEditing((prev) => {
      const next = new Set(prev);
      if (!next.delete(row.id)) next.add(row.id);
      return next;
    });
  }

  async function patch(row: Finding, body: { text?: string; status?: string }) {
    setBusy((prev) => new Set(prev).add(row.id));
    try {
      await updateFinding(row.id, body);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not update ${row.id}`);
    } finally {
      setBusy((prev) => {
        const next = new Set(prev);
        next.delete(row.id);
        return next;
      });
    }
  }

  /** Save then approve, as two calls. Sending `text` alone is deliberately not
   *  an approval (D20), so approving edited text has to say both things. */
  async function approve(row: Finding) {
    const text = currentText(row);
    if (!text.trim()) return; // the backend 422s on this; don't pretend it could work
    await patch(row, text === row.text ? { status: "approved" } : { text, status: "approved" });
    setEditing((prev) => {
      const next = new Set(prev);
      next.delete(row.id);
      return next;
    });
  }

  return (
    <section className={styles.panel} aria-label={title}>
      <h2 className={styles.title}>{title}</h2>
      {error && <ErrorBanner message={error} />}
      {rows === null && !error && <p className={styles.muted}>Loading…</p>}
      {rows !== null && rows.length === 0 && <p className={styles.muted}>{empty}</p>}

      {rows?.map((row) => {
        const isEditing = editing.has(row.id);
        const text = currentText(row);
        const working = busy.has(row.id);
        const edited = row.original_text !== null && row.text !== row.original_text;
        return (
          <article key={row.id} className={styles.finding} data-status={row.status}>
            <header className={styles.head}>
              <Badge>{STATUS_LABEL[row.status] ?? row.status}</Badge>
              <span className={styles.when}>{new Date(row.created_at).toLocaleString()}</span>
              {edited && <span className={styles.edited}>edited from the original draft</span>}
            </header>

            {isEditing ? (
              <Textarea
                value={text}
                rows={12}
                aria-label={`Edit finding ${row.id}`}
                onChange={(e) => setEdits((prev) => ({ ...prev, [row.id]: e.target.value }))}
              />
            ) : (
              <div className={styles.prose}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
              </div>
            )}

            <div className={styles.actions}>
              <Button size="sm" variant="ghost" onClick={() => toggleEdit(row)}>
                {isEditing ? "Done editing" : "Edit"}
              </Button>
              <Button
                size="sm"
                loading={working}
                disabled={!text.trim()}
                onClick={() => void approve(row)}
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="ghost"
                loading={working}
                onClick={() => void patch(row, { status: "rejected" })}
              >
                Reject
              </Button>
            </div>
          </article>
        );
      })}
    </section>
  );
}
