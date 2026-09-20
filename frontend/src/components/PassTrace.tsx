import type { AnalystPassOut, JudgePassOut, MessageTraceOut, PassTraceOut } from "../types";
import { Badge } from "../ui";
import ChartList from "./ChartList";
import styles from "./PassTrace.module.css";

function costLabel(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

function metaLine(role: string, p: AnalystPassOut | JudgePassOut): string {
  return `${role}: ${p.model} · ${p.tokens_in} in / ${p.tokens_out} out · ${p.latency_ms} ms · ${costLabel(p.cost_usd)}`;
}

function scoreBadge(score: number | null) {
  if (score === null) return <Badge tone="danger">judge failed</Badge>;
  // Display heuristic only — not the loop's acceptance decision.
  const tone: "accent" | "neutral" = score >= 80 ? "accent" : "neutral";
  return <Badge tone={tone}>judge {score}/100</Badge>;
}

function PassBlock({ pass }: { pass: PassTraceOut }) {
  const { analyst, judge } = pass;
  return (
    <details className={styles.pass}>
      <summary className={styles.passHeader}>
        <span className={styles.passTitle}>Pass {pass.pass_no}</span>
        {scoreBadge(judge.score)}
      </summary>
      <div className={styles.passBody}>
        {analyst.interpretation && <p className={styles.interp}>{analyst.interpretation}</p>}
        <ChartList charts={pass.charts} />
        {pass.errors.length > 0 && (
          <ul className={styles.errors}>
            {pass.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        )}
        {judge.feedback && <p className={styles.feedback}>Feedback: {judge.feedback}</p>}
        {judge.gaps.length > 0 && (
          <ul className={styles.gaps}>
            {judge.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        )}
        {pass.revision_instruction && (
          <p className={styles.revision}>Revision fed to next pass: {pass.revision_instruction}</p>
        )}
        <p className={styles.meta}>{metaLine("Analyst", analyst)}</p>
        <p className={styles.meta}>{metaLine("Judge", judge)}</p>
      </div>
    </details>
  );
}

interface Props {
  trace?: MessageTraceOut | null;
}

export default function PassTrace({ trace }: Props) {
  if (!trace || trace.passes.length === 0) return null;
  const n = trace.passes.length;
  return (
    <details className={styles.trace}>
      <summary className={styles.traceHeader}>
        Loop trace ({n} pass{n === 1 ? "" : "es"})
      </summary>
      <div className={styles.passes}>
        {trace.passes.map((p) => (
          <PassBlock key={p.pass_no} pass={p} />
        ))}
      </div>
    </details>
  );
}
