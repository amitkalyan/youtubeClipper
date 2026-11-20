import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AnalysisList } from "./pages/AnalysisList";
import { ComingSoon } from "./pages/ComingSoon";
import { Dashboard } from "./pages/Dashboard";
import { Highlights } from "./pages/Highlights";
import { History } from "./pages/History";
import { MetadataEditor } from "./pages/MetadataEditor";
import { NewProject } from "./pages/NewProject";
import { Preview } from "./pages/Preview";
import { Settings } from "./pages/Settings";
import { Shorts } from "./pages/Shorts";
import { Thumbnails } from "./pages/Thumbnails";
import { VideoAnalysis } from "./pages/VideoAnalysis";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new" element={<NewProject />} />
        <Route path="/analysis" element={<AnalysisList />} />
        <Route path="/projects/:projectId" element={<VideoAnalysis />} />
        <Route path="/history" element={<History />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/highlights" element={<Highlights />} />
        <Route path="/shorts" element={<Shorts />} />
        <Route path="/preview" element={<Preview />} />
        <Route path="/thumbnails" element={<Thumbnails />} />
        <Route path="/metadata" element={<MetadataEditor />} />
        <Route
          path="*"
          element={
            <ComingSoon
              title="Page not found"
              phase="Clipper"
              summary="That address is not part of this app."
            />
          }
        />
      </Routes>
    </Layout>
  );
}
