import { Panel, PageHeader, MetricCard, EmptyState, StatusPill } from "../components/Panel";
import { usePolling } from "../hooks/useLiveMetrics";

const SERVICES = [
  { name: "EKS",         description: "Managed Kubernetes — runs all 7 services" },
  { name: "EC2",         description: "Worker nodes for the cluster" },
  { name: "ECR",         description: "Container registry — 7 images" },
  { name: "DynamoDB",    description: "Users, decisions, audit log" },
  { name: "S3",          description: "Model storage" },
  { name: "CloudWatch",  description: "Logs + metrics" },
  { name: "SNS",         description: "Critical alerts" },
  { name: "IAM",         description: "Service roles" },
  { name: "ALB",         description: "Public ingress load balancer" },
  { name: "Lambda",      description: "Nightly log archival to S3" },
  { name: "VPC",         description: "Networking layer" },
  { name: "CloudTrail",  description: "AWS API audit log" },
];

export default function AWS() {
  const audit = usePolling("/api/scaling-events?n=20", 5000);

  return (
    <>
      <PageHeader title="AWS"
        description="12 AWS services integrated. Every audited operation is persisted to DynamoDB." />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <MetricCard label="Services integrated" value="12" />
        <MetricCard label="Region" value="us-east-1" />
        <MetricCard label="ECR repositories" value="7" />
        <MetricCard label="Audited operations" value={audit?.events?.length ?? "—"} />
      </div>

      <Panel title="Integrated AWS services" subtitle="real, working integrations" className="mb-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {SERVICES.map((s) => (
            <div key={s.name} className="border border-border rounded p-3 hover:bg-bg-200 transition-colors">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium">{s.name}</span>
                <span className="dot dot-ok" />
              </div>
              <p className="text-[11px] text-fg-subtle">{s.description}</p>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Audit log" subtitle="from executor service · DynamoDB-backed">
        {!audit?.events?.length
          ? <EmptyState title="No mutations yet"
                        description="Operations the RL agent triggers appear here." />
          : <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-fg-subtle uppercase">
                  <th className="pb-2 font-medium">Time</th>
                  <th className="pb-2 font-medium">Action</th>
                  <th className="pb-2 font-medium">Severity</th>
                  <th className="pb-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {audit.events.map((e, i) => (
                  <tr key={i} className="row-hover border-t border-border">
                    <td className="py-2 mono text-[11px] text-fg-muted">
                      {new Date((e.ts ?? 0) * 1000).toLocaleTimeString()}
                    </td>
                    <td className="py-2 mono text-xs">{e.kind}</td>
                    <td className="py-2"><StatusPill status={e.severity === "warning" ? "warning" : "ok"} /></td>
                    <td className="py-2 text-xs text-fg-muted">{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>}
      </Panel>
    </>
  );
}
