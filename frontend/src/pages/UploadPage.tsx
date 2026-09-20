import { useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createChat, uploadDataset } from "../api";
import ErrorBanner from "../components/ErrorBanner";
import AppShell from "../components/AppShell";
import { Button, Card } from "../ui";
import styles from "./UploadPage.module.css";

export default function UploadPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(e.target.files ?? []));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (files.length === 0 || pending) return;
    setPending(true);
    setError(null);
    try {
      const datasetIds: string[] = [];
      for (const file of files) {
        const dataset = await uploadDataset(file);
        datasetIds.push(dataset.id);
      }
      const chat = await createChat(datasetIds);
      navigate(`/c/${chat.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setPending(false);
    }
  }

  return (
    <AppShell width="upload">
      <Card>
        <div className={styles.hero}>
          <h1>CSV Analysis Assistant</h1>
          <p>Upload one or more CSVs to start asking questions about them.</p>
        </div>
        <form className={styles.form} onSubmit={handleSubmit}>
          <label className={styles.fileLabel}>
            <input
              className={styles.fileInput}
              type="file"
              accept=".csv"
              multiple
              aria-label="CSV files"
              onChange={handleFileChange}
            />
            <span aria-hidden="true">
              {files.length === 0
                ? "Choose CSV files"
                : files.length === 1
                  ? "Choose a different file"
                  : "Choose different files"}
            </span>
          </label>
          {files.length > 0 && (
            <p className={styles.fileNames}>{files.map((f) => f.name).join(", ")}</p>
          )}
          <Button type="submit" disabled={files.length === 0} loading={pending}>
            {pending ? "Uploading…" : "Upload"}
          </Button>
        </form>
        {error && <ErrorBanner message={error} />}
      </Card>
    </AppShell>
  );
}
