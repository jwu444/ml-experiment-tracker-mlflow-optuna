import { forwardRef, type ButtonHTMLAttributes } from "react";
import styles from "./Button.module.css";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "ghost";
  size?: "sm" | "md";
  loading?: boolean;
}

// forwardRef because Radix's `asChild` slots (Dialog.Trigger and friends) hand
// the child a ref and use it to return focus to the trigger when the overlay
// closes. A plain function component drops it, which React warns about and which
// silently strands keyboard focus on <body>.
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      {...rest}
      ref={ref}
      className={[styles.btn, className].filter(Boolean).join(" ")}
      data-variant={variant}
      data-size={size}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
    >
      {loading && <span className={styles.spinner} aria-hidden="true" />}
      {children}
    </button>
  );
});
