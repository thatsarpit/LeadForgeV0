import { useEffect, useState } from "react";
import { Bell, Mail, ShieldCheck } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import useTheme from "../../hooks/useTheme";

const PREFS_KEY = "engyne_client_prefs_v1";

const DEFAULT_PREFS = {
  updates: true,
  incidentAlerts: true,
  weeklyDigest: false,
};

function loadPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    return raw ? JSON.parse(raw) : DEFAULT_PREFS;
  } catch (err) {
    return DEFAULT_PREFS;
  }
}

export default function ClientSettings() {
  const { user } = useAuth();
  const { theme } = useTheme();
  const [prefs, setPrefs] = useState(loadPrefs);

  useEffect(() => {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  }, [prefs]);

  const togglePref = (key) => {
    setPrefs((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="engyne-page">
      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Account</div>
            <div className="engyne-card-title">Workspace identity</div>
            <div className="engyne-card-helper">
              Signed in with your invited Google account.
            </div>
          </div>
          <ShieldCheck size={18} className="text-[var(--engyne-muted)]" />
        </div>
        <div className="engyne-detail-grid">
          <div>
            <div className="engyne-detail-label">User</div>
            <div className="engyne-detail-value">{user?.sub || "-"}</div>
          </div>
          <div>
            <div className="engyne-detail-label">Role</div>
            <div className="engyne-detail-value">{user?.role || "client"}</div>
          </div>
          <div>
            <div className="engyne-detail-label">Theme mode</div>
            <div className="engyne-detail-value">Auto ({theme})</div>
          </div>
        </div>
      </section>

      <section className="engyne-panel-soft engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Notifications</div>
            <div className="engyne-card-title">Stay in sync</div>
            <div className="engyne-card-helper">
              We'll send updates and downtime notices to your inbox.
            </div>
          </div>
          <Bell size={18} className="text-[var(--engyne-muted)]" />
        </div>
        <div className="engyne-toggle-list">
          <button className="engyne-toggle" onClick={() => togglePref("updates")}>
            <span>Product updates & releases</span>
            <span className={prefs.updates ? "engyne-toggle-pill is-on" : "engyne-toggle-pill"}>
              {prefs.updates ? "On" : "Off"}
            </span>
          </button>
          <button className="engyne-toggle" onClick={() => togglePref("incidentAlerts")}>
            <span>Downtime + incident alerts</span>
            <span
              className={
                prefs.incidentAlerts ? "engyne-toggle-pill is-on" : "engyne-toggle-pill"
              }
            >
              {prefs.incidentAlerts ? "On" : "Off"}
            </span>
          </button>
          <button className="engyne-toggle" onClick={() => togglePref("weeklyDigest")}>
            <span>Weekly lead summary</span>
            <span
              className={
                prefs.weeklyDigest ? "engyne-toggle-pill is-on" : "engyne-toggle-pill"
              }
            >
              {prefs.weeklyDigest ? "On" : "Off"}
            </span>
          </button>
        </div>
      </section>

      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Email channel</div>
            <div className="engyne-card-title">Primary communications</div>
            <div className="engyne-card-helper">
              Maintenance notices and run summaries are delivered via Engyne updates.
            </div>
          </div>
          <Mail size={18} className="text-[var(--engyne-muted)]" />
        </div>
        <div className="engyne-muted">
          Emails are sent from invite@engyne.space and update@engyne.space.
        </div>
      </section>
    </div>
  );
}
