import type { ButtonHTMLAttributes } from "react";
import styles from "./IconButton.module.css";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
}

export function IconButton({ label, className, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      className={[styles.button, className].filter(Boolean).join(" ")}
      aria-label={label}
    />
  );
}
