import {
  Play,
  Pause,
  RotateCw,
  Activity,
  AlertTriangle,
  Loader2,
  Lock,
} from "lucide-react";

/**
 * SlotCard — FINAL
 * --------------------------------------------------
 * • Single-slot authority component
 * • Backend is the single source of truth
 * • Observer + Busy UX hardened
 * • No mock state, no timers, no assumptions
 */

export default function SlotCard({
  slot,
  isObserver,
  onStart,
  onStop,
  onRestart,
}) {
  const isBusy = Boolean(slot.busy);
  const controlsLocked = isObserver || isBusy;

  const STATUS_STYLES = {
    RUNNING: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    STOPPED: "text-zinc-400 bg-zinc-500/10 border-zinc-500/20",
    ERROR: "text-rose-400 bg-rose-500/10 border-rose-500/20",
    STARTING:
      "text-blue-400 bg-blue-500/10 border-blue-500/20 animate-pulse",
    STOPPING:
      "text-amber-400 bg-amber-500/10 border-amber-500/20 animate-pulse",
  };

  const statusClass =
    STATUS_STYLES[slot.status] ||
    STATUS_STYLES.STOPPED;

  const heartbeatAge =
    slot.last_heartbeat
      ? Math.floor(
          (Date.now() -
            new Date(slot.last_heartbeat).getTime()) /
            1000
        )
      : null;

  const heartbeatColor =
    heartbeatAge === null
      ? "text-zinc-600"
      : heartbeatAge < 5
      ? "text-emerald-400"
      : heartbeatAge < 15
      ? "text-amber-400"
      : "text-rose-400";

  return (
    <div className={`relative flex flex-col gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 transition hover:border-zinc-700 ${isBusy ? "opacity-80 cursor-wait" : ""}`}>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] font-mono text-zinc-500">
            {slot.slot_id}
          </div>
          <div className="text-sm font-semibold text-zinc-200">
            Worker Slot
          </div>
        </div>

        <span
          className={`px-2 py-0.5 rounded border text-[10px] font-bold ${statusClass}`}
        >
          {slot.status}
        </span>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-3 text-xs">
        <Metric label="Uptime">
          {slot.uptime_seconds
            ? `${Math.floor(slot.uptime_seconds / 60)}m`
            : "—"}
        </Metric>

        <Metric label="Throughput">
          {slot.metrics?.throughput ?? 0}/m
        </Metric>

        <Metric label="CPU">
          {slot.metrics?.cpu ?? 0}%
        </Metric>

        <Metric label="Memory">
          {slot.metrics?.memory ?? 0} MB
        </Metric>
      </div>

      {/* Heartbeat */}
      <div className={`flex items-center gap-2 text-[11px] ${heartbeatColor}`}>
        <Activity size={12} />
        {heartbeatAge === null
          ? "No heartbeat"
          : `Heartbeat ${heartbeatAge}s ago`}
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-3 border-t border-zinc-800">
        {slot.status === "RUNNING" && (
          <>
            <ActionButton
              disabled={controlsLocked}
              onClick={onStop}
              icon={Pause}
              label={isBusy ? "Stopping…" : "Stop"}
            />
            <ActionButton
              disabled={controlsLocked}
              onClick={onRestart}
              icon={RotateCw}
              label={isBusy ? "Restarting…" : "Restart"}
            />
          </>
        )}

        {slot.status === "STOPPED" && (
          <ActionButton
            disabled={controlsLocked}
            onClick={onStart}
            icon={Play}
            label={isBusy ? "Starting…" : "Start"}
            primary
          />
        )}

        {slot.status === "ERROR" && (
          <ActionButton
            disabled={controlsLocked}
            onClick={onRestart}
            icon={AlertTriangle}
            label={isBusy ? "Recovering…" : "Recover"}
            danger
          />
        )}
      </div>

      {/* Busy Overlay */}
      {isBusy && (
        <Overlay>
          <Loader2 className="animate-spin" size={16} />
          Executing command…
        </Overlay>
      )}

      {/* Observer Overlay */}
      {isObserver && !isBusy && (
        <Overlay subtle>
          <Lock size={14} />
          Observer mode — controls locked
        </Overlay>
      )}
    </div>
  );
}

/* ---------- Subcomponents ---------- */

function Metric({ label, children }) {
  return (
    <div>
      <div className="text-zinc-500">{label}</div>
      <div className="font-mono text-zinc-200">
        {children}
      </div>
    </div>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  disabled,
  primary,
  danger,
}) {
  const base =
    "flex-1 flex items-center justify-center gap-2 px-3 py-2 text-xs rounded border transition";

  const style = primary
    ? "bg-emerald-600/20 border-emerald-600 text-emerald-300 hover:bg-emerald-600/30"
    : danger
    ? "bg-rose-600/20 border-rose-600 text-rose-300 hover:bg-rose-600/30"
    : "bg-zinc-800 border-zinc-700 text-zinc-200 hover:bg-zinc-700";

  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={`${base} ${style} disabled:opacity-40 disabled:cursor-not-allowed`}
    >
      {disabled && label?.includes("…") ? (
        <Loader2 size={14} className="animate-spin" />
      ) : (
        <Icon size={14} />
      )}
      {label}
    </button>
  );
}

function Overlay({ children, subtle }) {
  return (
    <div
      className={`absolute inset-0 z-10 flex items-center justify-center gap-2 rounded-xl text-xs backdrop-blur-sm
        ${subtle ? "bg-zinc-950/40" : "bg-zinc-950/70"}
        text-zinc-400`}
    >
      {children}
    </div>
  );
}