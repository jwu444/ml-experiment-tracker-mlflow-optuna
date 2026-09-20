import type { HTMLAttributes } from "react";
import styles from "./Card.module.css";

export function Card({ children, className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={[styles.card, className].filter(Boolean).join(" ")}
    >
      {children}
    </div>
  );
}
