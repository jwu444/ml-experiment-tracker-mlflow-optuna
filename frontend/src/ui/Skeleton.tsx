import styles from "./Skeleton.module.css";

export interface SkeletonProps {
  variant?: "line" | "block";
  count?: number;
}

export function Skeleton({ variant = "line", count = 1 }: SkeletonProps) {
  const items = Array.from({ length: count }, (_, i) => i);

  return (
    <div className={styles.wrap} role="status" aria-label="Loading">
      {items.map((i) => (
        <div key={i} className={styles.item} data-variant={variant} />
      ))}
    </div>
  );
}
