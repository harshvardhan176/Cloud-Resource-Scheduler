import { useMemo } from "react";
import { Panel, PageHeader, MetricCard, EmptyState, StatusPill } from "../components/Panel";
import { MultiLine, AreaSeries } from "../components/Charts";
import { useLiveMetrics, useEventStream, usePolling } from "../hooks/useLiveMetrics";

const fmt = (n, d = 1) => (n == null ? "—" : Number(n).toFixed(d));
const fmtTime = (ts) =>
  new Date((ts || Date.now() / 1000) * 1000).toLocaleTimeString("en-US",
    { hour12: false, minute: "2-digit", second: "2-digit" });

export default function Operations() {
  const { snapshot, history, status } = useLiveMetrics();
  const { events } = useEventStream();
  const services = usePolling("/api/services", 8000);

  const chartData = useMemo(
    () => history.map((s) => ({
      t: fmtTime(s.ts),
      cpu: (s.cluster?.cpu_util ?? 0) * 100,
      memory: (s.cluster?.mem_util ?? 0) * 100,
      latency: s.cluster?.latency_p95_ms ?? 0,
    })),
    [history],
  );

  const c = snapshot?.cluster;

  return (
    <>
      <PageHeader title="Operations"
        description="Live cluster telemetry. All values come from real Prometheus / CloudWatch queries." />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <MetricCard label="CPU" value={c?.cpu_util != null ? fmt(c.cpu_util * 100) : null} unit="%" />
        <MetricCard label="Memory" value={c?.mem_util != null ? fmt(c.mem_util * 100) : null} unit="%" />
        <MetricCard label="Requests / min" value={c?.requests_per_min} hint={`p95 ${fmt(c?.latency_p95_ms, 0)} ms`} />
        <MetricCard label="EC2 instances" value={c?.ec2_instances} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
        <Panel title="CPU & Memory" subtitle="cluster average">
          {chartData.length > 1 ? (
            <MultiLine data={chartData} unit="%"
              series={[{ key: "cpu", label: "CPU" }, { key: "memory", label: "Memory" }]} />
          ) : <EmptyState title="Waiting for metrics"
                          description="Prometheus + WebSocket stream will populate within ~5 seconds." />}
        </Panel>
        <Panel title="Latency · p95" subtitle="end-to-end ms">
          {chartData.length > 1
            ? <AreaSeries data={chartData} dataKey="latency" unit=" ms" />
            : <EmptyState title="Waiting for metrics" />}
        </Panel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
        <Panel title="Scaling events" subtitle="from executor service">
          {events.length === 0
            ? <EmptyState title="No scaling events yet"
                          description="Events appear when the RL agent triggers an action." />
            : <ul className="divide-y divide-border">
                {events.slice(0, 8).map((e, i) => (
                  <li key={i} className="py-2 flex items-center gap-3 text-sm">
                    <span className={`dot ${e.severity === "warning" ? "dot-warn" : "dot-ok"}`} />
                    <span className="mono text-[11px] text-fg-subtle w-16">{fmtTime(e.ts)}</span>
                    <span className="text-fg-muted w-28">{e.kind}</span>
                    <span className="text-fg flex-1">{e.message}</span>
                  </li>
                ))}
              </ul>}
        </Panel>
        <Panel title="Service health" subtitle="live probes">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-fg-subtle uppercase">
                <th className="pb-2 font-medium">Service</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium text-right">Latency</th>
              </tr>
            </thead>
            <tbody>
              {services?.services?.length
                ? services.services.map((s) => (
                    <tr key={s.name} className="row-hover border-t border-border">
                      <td className="py-2 mono text-xs">{s.name}</td>
                      <td className="py-2"><StatusPill status={s.status} /></td>
                      <td className="py-2 text-right mono text-xs text-fg-muted">
                        {s.latency_ms == null ? "—" : `${s.latency_ms} ms`}
                      </td>
                    </tr>
                  ))
                : <tr><td colSpan="3" className="py-6 text-center text-fg-subtle text-xs">
                    Probing services…
                  </td></tr>}
            </tbody>
          </table>
        </Panel>
      </div>
    </>
  );
}
