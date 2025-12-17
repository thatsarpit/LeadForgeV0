// src/pages/Dashboard.jsx

import useSlots from "../hooks/useSlots";

export default function Dashboard() {
  const {
    slots,
    loading,
    error,
    refresh,
    start,
    pause,
    stop,
    observer,
    actionLoading,
  } = useSlots();

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6">
      
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold tracking-tight">
          LeadForge — Client Dashboard
        </h1>

        <button
          onClick={refresh}
          className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-sm font-medium"
        >
          Refresh
        </button>
      </div>

      {/* States */}
      {loading && (
        <div className="text-zinc-400">Loading slots…</div>
      )}

      {error && (
        <div className="text-red-500">Error: {error}</div>
      )}

      {/* Slots */}
      {!loading && !error && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {slots.map((slot) => {
            const busy = actionLoading === slot.slot_id;

            return (
              <div
                key={slot.slot_id}
                className="border border-zinc-800 rounded-lg p-4 bg-zinc-900 flex flex-col gap-4"
              >
                {/* Header */}
                <div className="flex justify-between items-center">
                  <h2 className="font-semibold">{slot.slot_id}</h2>
                  <span
                    className={`text-xs px-2 py-1 rounded ${
                      slot.status === "RUNNING"
                        ? "bg-emerald-500/20 text-emerald-400"
                        : slot.status === "PAUSED"
                        ? "bg-amber-500/20 text-amber-400"
                        : "bg-zinc-700 text-zinc-300"
                    }`}
                  >
                    {slot.status}
                  </span>
                </div>

                {/* Meta */}
                <div className="text-xs text-zinc-400 space-y-1">
                  <div>Auto Resume: {slot.auto_resume ? "ON" : "OFF"}</div>
                  <div>
                    Last Heartbeat: {slot.last_heartbeat || "—"}
                  </div>
                </div>

                {/* Controls */}
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <button
                    onClick={() => start(slot.slot_id)}
                    disabled={busy}
                    className="px-3 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm"
                  >
                    Start
                  </button>

                  <button
                    onClick={() => pause(slot.slot_id)}
                    disabled={busy}
                    className="px-3 py-2 rounded bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-sm"
                  >
                    Pause
                  </button>

                  <button
                    onClick={() => stop(slot.slot_id)}
                    disabled={busy}
                    className="px-3 py-2 rounded bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-sm"
                  >
                    Stop
                  </button>

                  <button
                    onClick={() => observer(slot.slot_id)}
                    disabled={busy}
                    className="px-3 py-2 rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 text-sm"
                  >
                    Observer
                  </button>
                </div>

                {busy && (
                  <div className="text-xs text-zinc-500 text-center pt-1">
                    Applying command…
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}