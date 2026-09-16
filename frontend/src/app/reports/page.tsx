"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { TASK_STATUSES } from "@/lib/types";
import type { CumulativeFlowPoint, CycleTimePoint, LeadTimePoint, ThroughputBucket } from "@/lib/types";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"];
const GRID = "var(--border)";
const TICK = { fill: "var(--text-muted)", fontSize: 11 };

function mean(values: number[]): number {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
}

function stdDev(values: number[], avg: number): number {
  if (values.length < 2) return 0;
  const variance = values.reduce((sum, v) => sum + (v - avg) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

export default function ReportsPage() {
  const [cycleTime, setCycleTime] = useState<CycleTimePoint[]>([]);
  const [leadTime, setLeadTime] = useState<LeadTimePoint[]>([]);
  const [throughput, setThroughput] = useState<ThroughputBucket[]>([]);
  const [cfd, setCfd] = useState<CumulativeFlowPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.reportCycleTime().then(setCycleTime).catch((e) => setError(e.message));
    api.reportLeadTime().then(setLeadTime).catch(console.error);
    api.reportThroughput().then(setThroughput).catch(console.error);
    api.reportCumulativeFlow().then(setCfd).catch(console.error);
  }, []);

  const controlPoints = cycleTime.map((p) => ({
    date: new Date(p.completed_at).toLocaleDateString(),
    hours: +(p.cycle_time_seconds / 3600).toFixed(2),
    title: p.title,
  }));
  const controlHours = controlPoints.map((p) => p.hours);
  const controlMean = mean(controlHours);
  const controlStd = stdDev(controlHours, controlMean);

  const cycleBuckets = [
    { label: "< 1h", max: 1 },
    { label: "1–4h", max: 4 },
    { label: "4–8h", max: 8 },
    { label: "8–24h", max: 24 },
    { label: "> 24h", max: Infinity },
  ].map((bucket, i, arr) => {
    const min = i === 0 ? 0 : arr[i - 1].max;
    const count = controlHours.filter((h) => h > min && h <= bucket.max).length;
    return { label: bucket.label, count };
  });

  const leadPoints = leadTime.map((p) => ({
    date: new Date(p.completed_at).toLocaleDateString(),
    hours: +(p.lead_time_seconds / 3600).toFixed(2),
    title: p.title,
  }));

  const cfdData = cfd.map((p) => ({ date: p.date, ...p.counts }));

  return (
    <main className="page">
      <h1>Reports</h1>
      {error && <p className="board-error">{error} — log in first at /login</p>}
      <div className="reports-grid">
        <div className="report-card">
          <h2>Control chart — cycle time per task</h2>
          {controlPoints.length === 0 ? (
            <p className="report-card__empty">No completed tasks yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <ScatterChart margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={TICK} />
                <YAxis dataKey="hours" tick={TICK} unit="h" />
                <Tooltip
                  contentStyle={{ background: "var(--surface-alt)", border: `1px solid ${GRID}` }}
                  formatter={(value) => [`${value}h`, "Cycle time"]}
                />
                <ReferenceLine y={controlMean} stroke="var(--text-muted)" strokeDasharray="4 4" label="mean" />
                <ReferenceLine
                  y={controlMean + controlStd}
                  stroke="var(--status-warning)"
                  strokeDasharray="2 2"
                  label="UCL"
                />
                <Scatter data={controlPoints} fill={SERIES[0]} />
              </ScatterChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="report-card">
          <h2>Cycle time distribution</h2>
          {controlHours.length === 0 ? (
            <p className="report-card__empty">No completed tasks yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={cycleBuckets} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="label" tick={TICK} />
                <YAxis tick={TICK} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "var(--surface-alt)", border: `1px solid ${GRID}` }} />
                <Bar dataKey="count" fill={SERIES[0]} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="report-card">
          <h2>Lead time per task</h2>
          {leadPoints.length === 0 ? (
            <p className="report-card__empty">No completed tasks yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <ScatterChart margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={TICK} />
                <YAxis dataKey="hours" tick={TICK} unit="h" />
                <Tooltip
                  contentStyle={{ background: "var(--surface-alt)", border: `1px solid ${GRID}` }}
                  formatter={(value) => [`${value}h`, "Lead time"]}
                />
                <Scatter data={leadPoints} fill={SERIES[1]} />
              </ScatterChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="report-card">
          <h2>Throughput</h2>
          {throughput.length === 0 ? (
            <p className="report-card__empty">No completed tasks yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={throughput} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="period_start" tick={TICK} />
                <YAxis tick={TICK} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "var(--surface-alt)", border: `1px solid ${GRID}` }} />
                <Bar dataKey="completed_count" name="Completed" fill={SERIES[2]} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="report-card" style={{ gridColumn: "1 / -1" }}>
          <h2>Cumulative flow diagram</h2>
          {cfdData.length === 0 ? (
            <p className="report-card__empty">No tasks yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <AreaChart data={cfdData} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={TICK} />
                <YAxis tick={TICK} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "var(--surface-alt)", border: `1px solid ${GRID}` }} />
                <Legend wrapperStyle={{ fontSize: 12, color: "var(--text-muted)" }} />
                {TASK_STATUSES.map((s, i) => (
                  <Area
                    key={s.key}
                    type="monotone"
                    dataKey={s.key}
                    name={s.label}
                    stackId="1"
                    stroke={SERIES[i]}
                    fill={SERIES[i]}
                    fillOpacity={0.5}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </main>
  );
}
