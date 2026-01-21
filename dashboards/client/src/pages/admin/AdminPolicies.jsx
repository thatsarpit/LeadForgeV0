import { Shield, SlidersHorizontal } from "lucide-react";

export default function AdminPolicies() {
  return (
    <div className="engyne-page">
      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Global guardrails</div>
            <div className="engyne-card-title">Policies & limits</div>
            <div className="engyne-card-helper">
              Define stop conditions, lead caps, and auto-recovery behavior.
            </div>
          </div>
          <SlidersHorizontal size={18} className="text-[var(--engyne-muted)]" />
        </div>
        <div className="engyne-form-grid">
          <div>
            <div className="engyne-kicker">Lead caps</div>
            <div className="engyne-muted">
              Set a global maximum to prevent runaway captures.
            </div>
          </div>
          <div className="engyne-form-fields">
            <label className="engyne-field">
              <span>Max leads per day</span>
              <input className="engyne-input" type="number" min="50" defaultValue="600" />
            </label>
            <label className="engyne-field">
              <span>Auto-pause after errors</span>
              <input className="engyne-input" type="number" min="1" defaultValue="3" />
            </label>
          </div>
        </div>
      </section>

      <section className="engyne-panel-soft engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Safety automation</div>
            <div className="engyne-card-title">Fail-safe actions</div>
            <div className="engyne-card-helper">
              Control what happens when slots miss heartbeats or lose login sessions.
            </div>
          </div>
          <Shield size={18} className="text-[var(--engyne-muted)]" />
        </div>
        <div className="engyne-toggle-list">
          <button className="engyne-toggle">
            <span>Auto-pause on heartbeat stale</span>
            <span className="engyne-toggle-pill is-on">On</span>
          </button>
          <button className="engyne-toggle">
            <span>Notify admin on login-required</span>
            <span className="engyne-toggle-pill is-on">On</span>
          </button>
          <button className="engyne-toggle">
            <span>Restart slot after idle</span>
            <span className="engyne-toggle-pill">Off</span>
          </button>
        </div>
      </section>
    </div>
  );
}
