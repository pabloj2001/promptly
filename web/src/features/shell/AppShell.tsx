import { useEffect } from "react";
import {
  NavLink,
  Outlet,
  useNavigate,
  useParams,
} from "react-router-dom";
import { useUiStore } from "../../store";

const TABS = [
  { to: "design", label: "Design" },
  { to: "plan", label: "Plan" },
  { to: "build", label: "Build" },
];

export function AppShell() {
  const { project } = useParams();
  const navigate = useNavigate();
  const setActiveProject = useUiStore((s) => s.setActiveProject);

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
        <nav className="flex gap-1">
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
        </nav>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
