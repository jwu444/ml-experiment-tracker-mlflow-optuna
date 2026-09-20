import styles from "./ChartList.module.css";

interface Props {
  charts: string[];
}

export default function ChartList({ charts }: Props) {
  if (charts.length === 0) return null;
  return (
    <div className={styles.list}>
      {charts.map((c, i) => (
        <img key={i} src={`data:image/png;base64,${c}`} alt={`chart ${i + 1}`} />
      ))}
    </div>
  );
}
