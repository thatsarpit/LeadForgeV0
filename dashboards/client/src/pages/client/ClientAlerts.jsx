import { useMemo } from "react";
import { Bell, ShieldAlert } from "lucide-react";
import { useNavigate, useOutletContext } from "react-router-dom";

function heartbeatAgeSeconds(slot) {
  if (!slot?.last_heartbeat) return null;
  const ts = Date.parse(slot.last_heartbeat);
  if (Number.isNaN(ts)) return null;
  return Math.floor((Date.now() - ts) / 1000);
}

export default function ClientAlerts() {
  const { slots } = useOutletContext();
  const navigate = useNavigate();

  const alerts = useMemo(() => {
    const list = [];
    slots.forEach((slot) => {
      const phase = String(slot.metrics?.phase || "").toUpperCase();
      const heartbeatAge = heartbeatAgeSeconds(slot);

      if (slot.status === "ERROR") {
        list.push({
          id: `${slot.slot_id}-error`,
          tone: "danger",
          title: "Slot error",
          detail: `${slot.slot_id} - ${slot.node_id || "local"}`,
          action: "Review logs",
        });
      }
      if (phase === "LOGIN_REQUIRED") {
        list.push({
          id: `${slot.slot_id}-login`,
          tone: "warn",
          title: "Login required",
          detail: `${slot.slot_id} - Remote login needed`,
          action: "Open remote login",
        });
      }
      if (heartbeatAge && heartbeatAge > 20) {
        list.push({
          id: `${slot.slot_id}-heartbeat`,
          tone: "warn",
          title: "Heartbeat delayed",
          detail: `${slot.slot_id} - ${heartbeatAge}s since last ping`,
          action: "Check slot",
        });
      }
    });
    return list;
  }, [slots]);

  return (
    <div className="engyne-page">
      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Alerts inbox</div>
            <div className="engyne-card-title">Operational notifications</div>
            <div className="engyne-card-helper">
              Alerts surface anything that might pause or slow your lead capture.
            </div>
          </div>
          <Bell size={18} className="text-[var(--engyne-muted)]" />
        </div>
      </section>

      {alerts.length === 0 ? (
        <section className="engyne-panel-soft engyne-card">
          <div className="engyne-empty">All clear. No active alerts.</div>
        </section>
      ) : (
        <div className="engyne-alert-stack">
          {alerts.map((alert) => (
            <div key={alert.id} className={`engyne-alert engyne-alert--${alert.tone}`}>
              <div className="engyne-alert-icon">
                <ShieldAlert size={18} />
              </div>
              <div>
                <div className="engyne-alert-title">{alert.title}</div>
                <div className="engyne-alert-text">{alert.detail}</div>
              </div>
              {alert.action && (
                <button
                  className="engyne-btn engyne-btn--ghost engyne-btn--small"
                  onClick={() => navigate("/app/slots")}
                >
                  {alert.action}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
