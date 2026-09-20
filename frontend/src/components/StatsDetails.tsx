import { Button } from "../ui";
import styles from "./StatsDetails.module.css";

interface Props {
  stats: Record<string, unknown>[];
}

export default function StatsDetails({ stats }: Props) {
  if (stats.length === 0) return null;

  function handleDownload() {
    const blob = new Blob([JSON.stringify(stats, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "statistics.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <details className={styles.details}>
      <summary className={styles.summary}>Raw statistics</summary>
      <div className={styles.actions}>
        <Button type="button" variant="ghost" size="sm" onClick={handleDownload}>
          Download JSON
        </Button>
      </div>
      <pre className={styles.pre}>{JSON.stringify(stats, null, 2)}</pre>
    </details>
  );
}
