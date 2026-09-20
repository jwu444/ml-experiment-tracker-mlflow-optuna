import type { ReactNode } from "react";
import styles from "./Badge.module.css";

export interface BadgeProps {
  tone?: "neutral" | "accent" | "danger";
  children: ReactNode;
}

export function Badge({ tone = "neutral", children }: BadgeProps) {
  return (
    <span className={styles.badge} data-tone={tone}>
      {children}
    </span>
  );
}
