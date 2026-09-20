import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Button, Textarea } from "../ui";
import styles from "./QuestionBox.module.css";

interface Props {
  onSubmit: (question: string) => void;
  pending: boolean;
}

export default function QuestionBox({ onSubmit, pending }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || pending) return;
    onSubmit(trimmed);
    setValue("");
    // The autosize grows the textarea imperatively on input; clearing the value
    // doesn't shrink it, so reset the height back to a single row after sending.
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter submits; Shift+Enter inserts a newline. Ignore Enter mid-IME
    // composition so it commits the candidate instead of sending.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <Textarea
          ref={textareaRef}
          className={styles.input}
          rows={1}
          aria-label="Question"
          placeholder="Ask a question…  (Enter to send, Shift+Enter for a new line)"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={pending}
        />
        <Button
          className={styles.send}
          type="submit"
          size="sm"
          disabled={value.trim() === ""}
          loading={pending}
        >
          {pending ? "Asking…" : "Ask"}
        </Button>
      </div>
    </form>
  );
}
