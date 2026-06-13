import { useEffect, useState } from "react";
import {
  NavLink,
  Outlet,
  useNavigate,
  useParams,
} from "react-router-dom";
import { useUiStore } from "../../store";
import { SettingsDialog } from "./SettingsDialog";

const TABS = [
  { to: "design", label: "Design" },
  { to: "plan", label: "Plan" },
  { to: "build", label: "Build" },
];

export function AppShell() {
  const { project } = useParams();
  const navigate = useNavigate();
  const setActiveProject = useUiStore((s) => s.setActiveProject);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Keep the store's active project in sync with the route param so the API
  // client and React Query keys pick it up.
  useEffect(() => {
    setActiveProject(project ?? null);
  }, [project, setActiveProject]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <div className="flex items-center gap-4">
          <button
            className="text-sm font-bold text-slate-900 hover:text-blue-600"
            onClick={() => navigate("/")}
          >
            Promptly
          </button>
          <span className="text-slate-300">/</span>
          <span className="text-sm font-medium text-slate-700">{project}</span>
        </div>
        <nav className="flex items-center gap-1">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={`/p/${encodeURIComponent(project ?? "")}/${t.to}`}
              className={({ isActive }) =>
                `rounded-md px-3 py-1.5 text-sm font-medium ${
                  isActive
                    ? "bg-blue-100 text-blue-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`
              }
            >
              {t.label}
            </NavLink>
          ))}
          <button
            className="ml-2 rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            onClick={() => setSettingsOpen(true)}
            title="Project settings"
            aria-label="Project settings"
          >
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </nav>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
      {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
