import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";

const C = { accent: "#7c7cff", accent2: "#58a6ff", ok: "#3fb950",
            grid: "#1f1f1f", axis: "#454545", text: "#9b9b9b" };

function TT({ active, payload, label, unit = "" }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-border bg-bg-100 px-2.5 py-1.5 text-xs">
      {label !== undefined && <div className="text-fg-muted mono mb-1">{label}</div>}
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="dot" style={{ background: p.color }} />
          <span className="text-fg-muted">{p.name}</span>
          <span className="mono text-fg">{Number(p.value).toFixed(2)}{unit}</span>
        </div>
      ))}
    </div>
  );
}

export function AreaSeries({ data, dataKey, height = 180, unit = "" }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="g-accent" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.accent} stopOpacity={0.25} />
            <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={C.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="t" stroke={C.axis} fontSize={10} tickLine={false} axisLine={false} />
        <YAxis stroke={C.axis} fontSize={10} tickLine={false} axisLine={false} width={32} />
        <Tooltip content={<TT unit={unit} />} cursor={{ stroke: C.accent, strokeOpacity: 0.3 }} />
        <Area type="monotone" dataKey={dataKey} stroke={C.accent} strokeWidth={1.5}
              fill="url(#g-accent)" isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function MultiLine({ data, series, height = 200, unit = "" }) {
  const palette = [C.accent, C.accent2, C.ok];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="t" stroke={C.axis} fontSize={10} tickLine={false} axisLine={false} />
        <YAxis stroke={C.axis} fontSize={10} tickLine={false} axisLine={false} width={32} />
        <Tooltip content={<TT unit={unit} />} cursor={{ stroke: C.accent, strokeOpacity: 0.3 }} />
        <Legend verticalAlign="top" align="right" height={20} iconType="circle" iconSize={6}
                wrapperStyle={{ fontSize: 11, color: C.text, paddingBottom: 8 }} />
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.label}
                stroke={palette[i % palette.length]} strokeWidth={1.5}
                dot={false} isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function HBars({ data, height = 180 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 80, bottom: 0 }}>
        <CartesianGrid stroke={C.grid} strokeDasharray="2 4" horizontal={false} />
        <XAxis type="number" stroke={C.axis} fontSize={10} tickLine={false} axisLine={false} />
        <YAxis dataKey="label" type="category" stroke={C.text} fontSize={11}
               tickLine={false} axisLine={false} width={80} />
        <Tooltip content={<TT />} cursor={{ fill: C.accent, fillOpacity: 0.06 }} />
        <Bar dataKey="value" fill={C.accent} radius={[0, 2, 2, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}
