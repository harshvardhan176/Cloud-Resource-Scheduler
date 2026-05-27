export function Panel({ title, subtitle, action, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <header className="panel-header">
          <div>
            {title && <h3 className="panel-title">{title}</h3>}
            {subtitle && <p className="panel-subtitle">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function PageHeader({ title, description }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {description && <p className="text-sm text-fg-muted mt-1">{description}</p>}
    </div>
  );
}

export function MetricCard({ label, value, unit, hint }) {
  return (
    <div className="panel p-4">
      <span className="text-xs text-fg-muted">{label}</span>
      <div className="mt-2 flex items-baseline gap-1">
        <span className="text-2xl font-semibold mono">
          {value ?? <span className="text-fg-faint">—</span>}
        </span>
        {unit && value != null && <span className="text-xs text-fg-muted">{unit}</span>}
      </div>
      {hint && <p className="mt-1 text-[11px] text-fg-subtle">{hint}</p>}
    </div>
  );
}

export function EmptyState({ title, description }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <p className="text-sm text-fg-muted">{title}</p>
      {description && <p className="text-xs text-fg-subtle mt-1 max-w-md">{description}</p>}
    </div>
  );
}

export function StatusPill({ status, label }) {
  const cls =
    ["healthy", "ok", "success", "Running"].includes(status) ? "pill-ok" :
    ["degraded", "warning", "simulated", "Pending"].includes(status) ? "pill-warn" :
    ["unreachable", "error", "failed", "Failed"].includes(status) ? "pill-err" : "";
  return <span className={`pill ${cls}`}>{label || status}</span>;
}
