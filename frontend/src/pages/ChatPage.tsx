import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { getChatHistory, postChat } from "../api";
import type { ChatDatasetOut, ChatMessageOut } from "../types";
import ChatTurn from "../components/ChatTurn";
import QuestionBox from "../components/QuestionBox";
import ErrorBanner from "../components/ErrorBanner";
import DatasetChips from "../components/DatasetChips";
import AppShell from "../components/AppShell";
import { Skeleton } from "../ui";
import styles from "./ChatPage.module.css";

export default function ChatPage() {
  const { chatId } = useParams<{ chatId: string }>();
  const [datasets, setDatasets] = useState<ChatDatasetOut[]>([]);
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  /** The optimistic turn currently in flight. One slot is right here: `pending`
   *  disables the box, so at most one question is ever outstanding. */
  const [sendingTurnId, setSendingTurnId] = useState<string | null>(null);
  /** Every turn that failed to send — a set, not a slot. Failures ACCUMULATE
   *  even though sends do not: asking again after a failure leaves the earlier
   *  question just as unsent as it was. A single slot silently un-marked it, so
   *  the thread went back to claiming a question had been delivered when the
   *  only copy of it was the one on screen. */
  const [failedTurnIds, setFailedTurnIds] = useState<Set<string>>(new Set());
  /** Distinguishes two optimistic turns created inside the same millisecond,
   *  which `Date.now()` alone does not. Colliding ids would make one turn's
   *  delivery state describe the other. */
  const localTurns = useRef(0);

  useEffect(() => {
    if (!chatId) return;
    let active = true;
    setLoading(true);
    setLoadError(null);
    getChatHistory(chatId)
      .then((history) => {
        if (!active) return;
        setDatasets(history.datasets);
        setMessages(history.messages);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setLoadError(err instanceof Error ? err.message : "Failed to load chat");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [chatId]);

  async function handleAsk(question: string) {
    if (!chatId) return;
    const userTurn: ChatMessageOut = {
      id: `local-${Date.now()}-${(localTurns.current += 1)}`,
      role: "user",
      content: question,
      charts: [],
      stats: [],
      errors: [],
    };
    setPending(true);
    setAskError(null);
    // Deliberately NOT clearing past failures: a new question says nothing about
    // whether an earlier one was delivered.
    // Show the question the moment it is asked, not when the answer lands (#50).
    // The judge-gated loop can run several passes, and `QuestionBox` clears its
    // input on submit — so until this the thread looked like the question had
    // never been received.
    setMessages((prev) => [...prev, userTurn]);
    setSendingTurnId(userTurn.id);
    try {
      const assistant = await postChat(chatId, question);
      setMessages((prev) => [...prev, assistant]);
    } catch (err: unknown) {
      setAskError(err instanceof Error ? err.message : "Request failed");
      // The turn stays — the question is otherwise destroyed, since QuestionBox
      // has already cleared it — but it is marked as not sent. Optimistic rows
      // are the one place `messages` is not a mirror of persisted history, and a
      // failed one would vanish on the next reload with nothing having said so.
      setFailedTurnIds((prev) => new Set(prev).add(userTurn.id));
    } finally {
      setSendingTurnId(null);
      setPending(false);
    }
  }

  function deliveryOf(m: ChatMessageOut): "sending" | "failed" | undefined {
    if (m.id === sendingTurnId) return "sending";
    if (failedTurnIds.has(m.id)) return "failed";
    return undefined;
  }

  if (loading) {
    return (
      <AppShell>
        <div className={styles.loading}>
          <Skeleton count={3} />
        </div>
      </AppShell>
    );
  }
  if (loadError) {
    return (
      <AppShell>
        <ErrorBanner message={loadError} />
      </AppShell>
    );
  }

  return (
    <AppShell topbarRight={<DatasetChips datasets={datasets} />}>
      {messages.length === 0 && (
        <p className={styles.empty}>Ask your first question about these datasets.</p>
      )}
      <div className={styles.messages}>
        {messages.map((m) => (
          <ChatTurn key={m.id} message={m} delivery={deliveryOf(m)} />
        ))}
      </div>
      {askError && <ErrorBanner message={askError} />}
      <QuestionBox onSubmit={handleAsk} pending={pending} />
    </AppShell>
  );
}
