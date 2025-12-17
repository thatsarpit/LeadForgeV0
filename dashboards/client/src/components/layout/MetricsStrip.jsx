import { useEffect, useState } from "react";
import { Server, Activity, PauseCircle, Cpu } from "lucide-react";
import { fetchSlots } from "../../services/api";

export default function MetricsStrip() {
  const [loading, setLoading] = useState(true);
  const [metrics, setMetrics] = useState({
    total: 0,
    running: 0,
    stopped: 0,
    busy: 0,
  });

  useEffect(() => {
    let alive = true;

    const fetchMetrics = async () => {
      try {
        const data = await fetchSlots();
        const slots = data.slots || [];

        if (!alive) return;

        setMetrics({
          total: slots.length,
          running: slots.filter(s => s.status === "RUNNING").length,
          stopped: slots.filter(s => s.status === "STOPPED").length,
          busy: slots.filter(s => s.busy === true).length,
        });

        setLoading(false);
      } catch (err) {
        console.error("[MetricsStrip] Failed to fetch metrics", err);
        setLoading(false);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 2000);

    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, []);

  const Metric = ({ icon: Icon, label, value, tone }) => (
    <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-zinc-900 border border-zinc-800">
      <Icon size={18} className="text-zinc-400" />
      <div className="flex flex-col">
        <span className="text-[10px] uppercase tracking-wide text-zinc-500">
          {label}
        </span>
        <span
          className={`text-sm font-mono font-semibold ${
            tone === "good"
              ? "text-emerald-400"
              : tone === "warn"
              ? "text-amber-400"
              : "text-zinc-200"
          }`}
        >
          {loading ? "—" : value}
        </span>
      </div>
    </div>
  );

  return (
    <section className="mb-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
      <Metric icon={Server} label="Total Slots" value={metrics.total} />
      <Metric icon={Activity} label="Running" value={metrics.running} tone="good" />
      <Metric icon={PauseCircle} label="Stopped" value={metrics.stopped} />
      <Metric icon={Cpu} label="Busy" value={metrics.busy} tone="warn" />
    </section>
  );
}