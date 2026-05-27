import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Activity, BrainCircuit, Cloud } from "lucide-react";
import { useLiveMetrics } from "../hooks/useLiveMetrics";

const NAV = [
  { to: "/ops",          label: "Operations",   icon: Activity },
  { to: "/intelligence", label: "Intelligence", icon: BrainCircuit },
  { to: "/aws",          label: "AWS",          icon: Cloud },
];

export default function Layout() {
  const { status } = useLiveMetrics();
  const loc = useLocation();
  const current = NAV.find((n) => loc.pathname.startsWith(n.to)) || NAV[0];

  return (
    <div className="h-screen flex bg-bg text-fg">
      <aside className="w-56 shrink-0 border-r border-border bg-bg-50 flex flex-col">
        <div className="h-12 px-4 flex items-center gap-2 border-b border-border">
          <div className="w-5 h-5 rounded bg-accent flex items-center justify-center">
            <span className="text-white text-[10px] font-bold">CB</span>
          </div>
          <span className="text-sm font-medium">CloudBrain</span>
        </div>
        <nav className="flex-1 py-3 px-2 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-2.5 py-1.5 rounded text-sm ${
                  isActive ? "bg-bg-200 text-fg" : "text-fg-muted hover:bg-bg-100 hover:text-fg"
                }`}>
              <Icon size={15} strokeWidth={1.75} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="px-3 py-3 border-t border-border text-[11px] text-fg-subtle flex justify-between">
          <span>v1.0.0</span>
          <span className="mono">dev</span>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-12 px-5 border-b border-border flex items-center justify-between bg-bg-50">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-fg-muted">CloudBrain</span>
            <span className="text-fg-faint">/</span>
            <span className="text-fg font-medium">{current.label}</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            <span className={`dot ${status === "live" ? "dot-ok" : status === "error" ? "dot-err" : "dot-warn"}`} />
            <span className="text-fg-muted">
              {status === "live" ? "Live" : status === "error" ? "Disconnected" : "Connecting"}
            </span>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-[1400px] mx-auto px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
