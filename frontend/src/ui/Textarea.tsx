import { forwardRef, useCallback, type TextareaHTMLAttributes } from "react";
import styles from "./Textarea.module.css";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, onInput, ...rest }, ref) {
  const autosize = useCallback(
    (e: React.FormEvent<HTMLTextAreaElement>) => {
      const el = e.currentTarget;
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
      onInput?.(e);
    },
    [onInput],
  );

  return (
    <textarea
      {...rest}
      ref={ref}
      className={[styles.textarea, className].filter(Boolean).join(" ")}
      onInput={autosize}
    />
  );
});
