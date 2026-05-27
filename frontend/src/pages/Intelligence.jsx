import { useEffect, useMemo, useState } from "react";
import { Panel, PageHeader, MetricCard, EmptyState, StatusPill } from "../components/Panel";
import { MultiLine, HBars } from "../components/Charts";
import { useLiveMetrics, useEventStream, usePolling } from "../hooks/useLiveMetrics";

const fmt = (n, d = 2) => (n == null ? "—" : Number(n).toFixed(d));
const fmtTime = (ts) =>
  new Date((ts || Date.now() / 1000) * 1000).toLocaleTimeString("en-US",
    { hour12: false, minute: "2-digit", second: "2-digit" });

export default function Intelligence() {
  const { history } = useLiveMetrics();
  const { rlDecisions } = useEventStream();
  const models = usePolling("/ml/models", 10000);
  const agent = usePolling("/rl/agent", 15000);
  const [forecast, setForecast] = useState(null);

  useEffect(() => {
    if (history.length < 10) return;
    const recent = history.slice(-60).map((s) => s.cluster?.cpu_util ?? 0.4);
    fetch("/ml/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ history: recent.length >= 5 ? recent : [0.4,0.42,0.45,0.43,0.48], horizon: 30, metric: "cpu", model: "ensemble" }),
    }).then((r) => r.ok ? r.json() : null).then((d) => d && setForecast(d)).catch(() => {});
  }, [Math.floor(history.length / 10)]);

  const chartData = forecast
    ? [
        ...history.slice(-60).map((s, i) => ({
          t: i - 60,
          actual: (s.cluster?.cpu_util ?? 0) * 100,
          predicted: null,
        })),
        ...forecast.values.map((v, i) => ({
          t: i, actual: null, predicted: v * 100,
        })),
      ]
    : history.slice(-60).map((s, i) => ({ t: i - 60, actual: (s.cluster?.cpu_util ?? 0) * 100 }));

  const actionDist = useMemo(() => {
    const counts = {};
    rlDecisions.forEach((d) => { counts[d.action] = (counts[d.action] ?? 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
      .map(([label, value]) => ({ label, value }));
  }, [rlDecisions]);

  return (
    <>
      <PageHeader title="Intelligence"
        description="ML forecast ensemble + RL scheduling agent. Both use real metrics as input." />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <MetricCard label="Forecast model" value={forecast?.model ?? "—"} hint="ensemble (LSTM + XGB + Prophet)" />
        <MetricCard label="MAE estimate" value={fmt(forecast?.mae_estimate, 3)} />
        <MetricCard label="RL algorithm" value={agent?.algo?.toUpperCase() ?? "—"}
          hint={agent?.is_heuristic ? "heuristic fallback" : "trained model"} />
        <MetricCard label="Decisions" value={rlDecisions.length} hint="recent" />
      </div>

      <Panel title="CPU forecast"
        subtitle="observed last 60 s vs predicted next 30 s · LSTM + XGBoost + Prophet ensemble"
        className="mb-3">
        {chartData.length > 1 ? (
          <MultiLine data={chartData} height={260} unit="%"
            series={[{ key: "actual", label: "Observed" }, { key: "predicted", label: "Forecast" }]} />
        ) : <EmptyState title="Collecting history"
                        description="Forecast appears once telemetry has accumulated." />}
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
        <Panel title="Model leaderboard">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-fg-subtle uppercase">
                <th className="pb-2 font-medium">Model</th>
                <th className="pb-2 font-medium text-right">MAE</th>
                <th className="pb-2 font-medium text-right">Weight</th>
                <th className="pb-2 font-medium text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {models?.models?.map((m) => (
                <tr key={m.name} className="row-hover border-t border-border">
                  <td className="py-2 mono text-xs">{m.name}</td>
                  <td className="py-2 text-right mono text-xs">{fmt(m.mae, 3)}</td>
                  <td className="py-2 text-right mono text-xs">{fmt(m.weight, 2)}</td>
                  <td className="py-2 text-right">
                    <StatusPill status={m.loaded ? "ok" : "warning"}
                                label={m.loaded ? "loaded" : "fallback"} />
                  </td>
                </tr>
              )) ?? <tr><td colSpan="4" className="py-6 text-center text-fg-subtle text-xs">Loading…</td></tr>}
            </tbody>
          </table>
        </Panel>

        <Panel title="RL action distribution" subtitle="recent decisions">
          {actionDist.length
            ? <HBars data={actionDist} height={200} />
            : <EmptyState title="No decisions yet" />}
        </Panel>
      </div>

      <Panel title="RL decision feed" subtitle="action · confidence · rationale">
        {rlDecisions.length === 0
          ? <EmptyState title="No decisions yet"
                        description="The scheduler publishes here as it serves actions." />
          : <ul className="divide-y divide-border">
              {rlDecisions.slice(0, 12).map((d, i) => (
                <li key={i} className="py-2.5 flex items-start gap-3 text-sm">
                  <span className="mono text-[11px] text-fg-subtle pt-0.5 w-16">{fmtTime(d.ts)}</span>
                  <span className="pill pill-info shrink-0">{d.action}</span>
                  <span className="text-fg-muted text-xs flex-1">{d.rationale ?? ""}</span>
                  <span className="mono text-[11px] text-fg-subtle">{fmt((d.confidence ?? 0) * 100, 0)}%</span>
                </li>
              ))}
            </ul>}
      </Panel>
    </>
  );
}
