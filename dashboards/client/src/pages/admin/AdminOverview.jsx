import { useMemo } from "react";
import { useOutletContext } from "react-router-dom";
import StatCard from "../../components/StatCard";

function heartbeatAgeSeconds(slot) {
  if (!slot?.last_heartbeat) return null;
  const ts = Date.parse(slot.last_heartbeat);
  if (Number.isNaN(ts)) return null;
  return Math.floor((Date.now() - ts) / 1000);
}

export default function AdminOverview() {
  const { slots, loading, error } = useOutletContext();

  const summary = useMemo(() => {
    const total = slots.length;
    const running = slots.filter((s) => s.status === "RUNNING").length;
    const stopped = slots.filter((s) => s.status === "STOPPED").length;
    const errors = slots.filter((s) => s.status === "ERROR" || s.metrics?.last_error).length;
    return { total, running, stopped, errors };
  }, [slots]);

  const loginRequired = useMemo(
    () => slots.filter((s) => String(s.metrics?.phase || "").toUpperCase() === "LOGIN_REQUIRED"),
    [slots]
  );

  const staleHeartbeats = useMemo(() => {
    return slots
      .map((slot) => ({ slot, age: heartbeatAgeSeconds(slot) }))
      .filter((entry) => Number.isFinite(entry.age) && entry.age > 20)
      .sort((a, b) => b.age - a.age)
      .slice(0, 6);
  }, [slots]);

  const topThroughput = useMemo(() => {
    return slots
      .slice()
      .sort((a, b) => Number(b.metrics?.throughput || 0) - Number(a.metrics?.throughput || 0))
      .slice(0, 6);
  }, [slots]);

  return (
    <div className="engyne-page">
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <StatCard label="Total slots" value={summary.total} tone="muted" helper="Fleet" />
        <StatCard label="Running" value={summary.running} tone="good" helper="Active" />
        <StatCard label="Stopped" value={summary.stopped} tone="muted" helper="Paused" />
        <StatCard label="Errors" value={summary.errors} tone="danger" helper="Needs attention" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_1fr] gap-4">
        <section className="engyne-panel-soft engyne-card">
          <div className="engyne-card-header">
            <div>
              <div className="engyne-kicker">Fleet health</div>
              <div className="engyne-card-title">Live system signals</div>
              <div className="engyne-card-helper">
                Track login requirements and heartbeat stability.
              </div>
            </div>
          </div>

          {loading && <div className="engyne-muted">Loading slots...</div>}
          {error && <div className="engyne-alert engyne-alert--danger">{error}</div>}

          {!loading && !error && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="engyne-mini-list">
                <div className="engyne-kicker">Login required</div>
                {loginRequired.length === 0 ? (
                  <div className="engyne-muted">None</div>
                ) : (
                  loginRequired.map((slot) => (
                    <div key={slot.slot_id} className="engyne-mini-row">
                      <span>{slot.slot_id}</span>
                      <span>{slot.node_id || "local"}</span>
                    </div>
                  ))
                )}
              </div>
              <div className="engyne-mini-list">
                <div className="engyne-kicker">Heartbeat stale</div>
                {staleHeartbeats.length === 0 ? (
                  <div className="engyne-muted">None</div>
                ) : (
                  staleHeartbeats.map(({ slot, age }) => (
                    <div key={slot.slot_id} className="engyne-mini-row">
                      <span>{slot.slot_id}</span>
                      <span>{age}s</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </section>

        <section className="engyne-panel-soft engyne-card">
          <div className="engyne-card-header">
            <div>
              <div className="engyne-kicker">Performance leaders</div>
              <div className="engyne-card-title">Top throughput</div>
              <div className="engyne-card-helper">
                Highest throughput across nodes.
              </div>
            </div>
          </div>
          {topThroughput.length === 0 ? (
            <div className="engyne-muted">No active slots yet.</div>
          ) : (
            <div className="engyne-leaderboard">
              {topThroughput.map((slot) => (
                <div key={slot.slot_id} className="engyne-leader-row">
                  <div>
                    <div className="engyne-slot-title">{slot.slot_id}</div>
                    <div className="engyne-slot-meta">
                      {slot.node_id || "local"} - {slot.status || "-"}
                    </div>
                  </div>
                  <div className="engyne-mono">
                    {Math.round(Number(slot.metrics?.throughput || 0))}/m
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
