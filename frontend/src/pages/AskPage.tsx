import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router-dom";

import { askAgent } from "../api";
import AppShell from "../components/AppShell";
import ErrorBanner from "../components/ErrorBanner";
import type { AgentAnswer, Retrieved } from "../types";
import { Button, Card, Textarea } from "../ui";
import styles from "./AskPage.module.css";

/** Where a citation goes. An `eda` hit is about a dataset and has no run; the
 *  other two are about a run and open its investigation. Switching on
 *  `source_type` rather than on whichever id happens to be non-null keeps the
 *  mapping readable when a hit carries several. */
function hrefFor(hit: Retrieved): string | null {
  if (hit.source_type === "eda") {
    return hit.dataset_id ? `/datasets/${hit.dataset_id}` : null;
  }
  return hit.experiment_id ? `/experiments/${hit.experiment_id}` : null;
}

function labelFor(hit: Retrieved): string {
  const what =
    hit.source_type === "eda"
      ? "EDA"
      : hit.source_type === "note"
        ? "Run note"
        : "Diagnostic";
  return `${what} · ${hit.source_id.slice(0, 8)}`;
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AgentAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    if (!question.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await askAgent(question));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    // Every page carries the shell itself; without it this one would render
    // with no nav rail — including the Agent category that links here.
    <AppShell width="chat">
      <div className={styles.page}>
        <h1>Ask about the experiment history</h1>
        <p className={styles.lede}>
          Answers come from <strong>approved</strong> run notes, EDA findings
          and diagnostics. Nothing that has not been reviewed is searched.
        </p>

        <form onSubmit={submit} className={styles.form}>
          <label htmlFor="agent-question">Question</label>
          <Textarea
            id="agent-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            placeholder="Which model did best on the revenue panel, and by how much?"
          />
          <Button type="submit" disabled={busy || !question.trim()}>
            {busy ? "Asking…" : "Ask"}
          </Button>
        </form>

        {error && <ErrorBanner message={error} />}

        {result && (
          <>
            {result.warnings.map((warning) => (
              <p key={warning} className={styles.warning} role="status">
                {warning}
              </p>
            ))}

            <Card className={styles.answer}>
              <ReactMarkdown>{result.answer}</ReactMarkdown>
            </Card>

            <h2>Sources</h2>
            {result.retrieved.length === 0 ? (
              <p className={styles.empty}>
                No sources — nothing approved matched this question.
              </p>
            ) : (
              <ul className={styles.sources}>
                {result.retrieved.map((hit) => {
                  const href = hrefFor(hit);
                  return (
                    <li
                      key={`${hit.source_type}:${hit.source_id}`}
                      data-source={hit.source_type}
                    >
                      {href ? (
                        <Link to={href}>{labelFor(hit)}</Link>
                      ) : (
                        <span>{labelFor(hit)}</span>
                      )}
                      <span className={styles.score}>
                        {hit.score.toFixed(2)}
                      </span>
                      <p className={styles.snippet}>{hit.snippet}</p>
                    </li>
                  );
                })}
              </ul>
            )}

            <details className={styles.trace}>
              <summary>
                Trace · {result.trace.steps.length} steps ·{" "}
                {result.trace.tokens_in + result.trace.tokens_out} tokens ·{" "}
                {result.trace.latency_ms} ms
              </summary>
              <ol>
                {result.trace.steps.map((step, index) => (
                  <li key={index} data-step={step.type}>
                    {step.type === "tool"
                      ? `${step.tool_name} — ${step.error ?? step.result_summary ?? ""}`
                      : `${step.model} — ${step.tokens_in} in / ${step.tokens_out} out`}
                  </li>
                ))}
              </ol>
            </details>
          </>
        )}
      </div>
    </AppShell>
  );
}
