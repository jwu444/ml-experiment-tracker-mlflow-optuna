import type { ChatDatasetOut } from "../types";
import { Badge } from "../ui";
import styles from "./DatasetChips.module.css";

interface Props {
  datasets: ChatDatasetOut[];
}

export default function DatasetChips({ datasets }: Props) {
  if (datasets.length === 0) return null;
  return (
    <ul className={styles.list} aria-label="Attached datasets">
      {datasets.map((d) => (
        <li key={d.id}>
          <Badge tone="accent">{d.name}</Badge>
        </li>
      ))}
    </ul>
  );
}
