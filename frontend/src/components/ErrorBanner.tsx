import styles from "./ErrorBanner.module.css";

interface Props {
  message: string;
}

export default function ErrorBanner({ message }: Props) {
  return (
    <p role="alert" className={styles.banner}>
      {message}
    </p>
  );
}
