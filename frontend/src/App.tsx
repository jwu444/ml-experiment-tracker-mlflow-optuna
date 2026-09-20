import { Routes, Route } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import ChatPage from "./pages/ChatPage";
import DatasetPage from "./pages/DatasetPage";
import ExperimentsPage from "./pages/ExperimentsPage";
import ExperimentDetailPage from "./pages/ExperimentDetailPage";
import AskPage from "./pages/AskPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<UploadPage />} />
      <Route path="/c/:chatId" element={<ChatPage />} />
      <Route path="/datasets/:datasetId" element={<DatasetPage />} />
      <Route path="/experiments" element={<ExperimentsPage />} />
      <Route path="/experiments/:experimentId" element={<ExperimentDetailPage />} />
      <Route path="/ask" element={<AskPage />} />
    </Routes>
  );
}
