import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessageOut } from "../types";
import ChartList from "./ChartList";
import StatsDetails from "./StatsDetails";
import ErrorBanner from "./ErrorBanner";
import styles from "./ChatTurn.module.css";
import PassTrace from "./PassTrace";

interface Props {
  message: ChatMessageOut;
  /** Delivery state of an optimistically-rendered turn (#50). A question is
   *  shown the moment it is asked, before the round trip finishes, so the turn
   *  has to say whether it is still in flight — otherwise the thread claims the
   *  message landed while the answer is still being generated. Omitted for every
   *  turn loaded from history, which is by definition delivered. */
  delivery?: "sending" | "failed";
}

const DELIVERY_LABEL: Record<"sending" | "failed", string> = {
  sending: "Sending… the answer can take a few passes.",
  failed: "Not sent — this question was not saved.",
};

export default function ChatTurn({ message, delivery }: Props) {
  return (
    <div className={styles.turn} data-role={message.role} data-delivery={delivery}>
      <span className={styles.role}>{message.role}</span>
      {message.content &&
        (message.role === "assistant" ? (
          // Assistant prose is Markdown; user questions are shown verbatim.
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        ) : (
          <p>{message.content}</p>
        ))}
      <ChartList charts={message.charts} />
      {message.errors.map((e, i) => (
        <ErrorBanner key={i} message={e} />
      ))}
      <StatsDetails stats={message.stats} />
      <PassTrace trace={message.trace} />
      {delivery && (
        <span className={styles.status} role="status">
          {DELIVERY_LABEL[delivery]}
        </span>
      )}
    </div>
  );
}
