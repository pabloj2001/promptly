import { Navigate, Route, Routes } from "react-router-dom";
import { ProjectPicker } from "./features/projects/ProjectPicker";
import { AppShell } from "./features/shell/AppShell";
import { DesignTab } from "./features/design/DesignTab";
import { PlanTab } from "./features/plan/PlanTab";
import { BuildTab } from "./features/build/BuildTab";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectPicker />} />
      <Route path="/p/:project" element={<AppShell />}>
        <Route index element={<Navigate to="design" replace />} />
        <Route path="design" element={<DesignTab />} />
        <Route path="plan" element={<PlanTab />} />
        <Route path="build/:taskId?" element={<BuildTab />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
