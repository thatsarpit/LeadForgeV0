import { useState } from "react";
import { Mail, Satellite, ShieldCheck } from "lucide-react";
import { sendMaintenanceNotice, sendUpdateNotice } from "../../services/api";

export default function AdminIntegrations() {
  const [maintenanceSubject, setMaintenanceSubject] = useState("Engyne Maintenance Notice");
  const [maintenanceBody, setMaintenanceBody] = useState(
    "We are performing scheduled maintenance right now. The Engyne system may be unavailable for a short window. We'll notify you as soon as service is restored."
  );
  const [updateSubject, setUpdateSubject] = useState("Engyne Product Update");
  const [updateBody, setUpdateBody] = useState(
    "We've shipped an update to Engyne. New dashboards and scheduler controls are now live."
  );
  const [status, setStatus] = useState("");
  const [sending, setSending] = useState(false);

  const handleSend = async (type) => {
    setStatus("");
    setSending(true);
    try {
      const payload =
        type === "maintenance"
          ? { subject: maintenanceSubject, message: maintenanceBody }
          : { subject: updateSubject, message: updateBody };
      const res =
        type === "maintenance"
          ? await sendMaintenanceNotice(payload)
          : await sendUpdateNotice(payload);
      const failed = res.failed?.length || 0;
      setStatus(
        failed
          ? `Sent with ${failed} failed deliveries.`
          : `Delivered to ${res.sent || 0} recipients.`
      );
    } catch (err) {
      setStatus("Unable to send email. Check SMTP configuration.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="engyne-page">
      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Email delivery</div>
            <div className="engyne-card-title">Brevo maintenance updates</div>
            <div className="engyne-card-helper">
              Send downtime notices, release updates, and onboarding reminders.
            </div>
          </div>
          <Mail size={18} className="text-[var(--engyne-muted)]" />
        </div>
        <div className="engyne-form-grid">
          <div>
            <div className="engyne-kicker">Sender profiles</div>
            <div className="engyne-muted">
              Invitations are sent from invite@engyne.space. Maintenance emails will use update@engyne.space.
            </div>
          </div>
          <div className="engyne-form-fields">
            <label className="engyne-field">
              <span>Maintenance template</span>
              <input className="engyne-input" type="text" defaultValue="Engyne Maintenance Notice" />
            </label>
            <label className="engyne-field">
              <span>Status updates</span>
              <input className="engyne-input" type="text" defaultValue="Engyne Release Update" />
            </label>
          </div>
        </div>
      </section>

      <section className="engyne-panel-soft engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Status broadcast</div>
            <div className="engyne-card-title">Client communication</div>
            <div className="engyne-card-helper">
              Send targeted maintenance notices and release updates.
            </div>
          </div>
          <Satellite size={18} className="text-[var(--engyne-muted)]" />
        </div>
        <div className="engyne-form-grid">
          <div>
            <div className="engyne-kicker">Maintenance notice</div>
            <div className="engyne-muted">
              Use this when the system is offline or degraded.
            </div>
          </div>
          <div className="engyne-form-fields">
            <label className="engyne-field">
              <span>Subject</span>
              <input
                className="engyne-input"
                type="text"
                value={maintenanceSubject}
                onChange={(event) => setMaintenanceSubject(event.target.value)}
              />
            </label>
            <label className="engyne-field">
              <span>Message</span>
              <textarea
                className="engyne-input engyne-textarea"
                rows="4"
                value={maintenanceBody}
                onChange={(event) => setMaintenanceBody(event.target.value)}
              />
            </label>
            <button
              className="engyne-btn engyne-btn--primary"
              onClick={() => handleSend("maintenance")}
              disabled={sending}
            >
              Send maintenance email
            </button>
          </div>
        </div>
        <div className="engyne-divider" />
        <div className="engyne-form-grid">
          <div>
            <div className="engyne-kicker">Release update</div>
            <div className="engyne-muted">
              Announce new product features or improvements.
            </div>
          </div>
          <div className="engyne-form-fields">
            <label className="engyne-field">
              <span>Subject</span>
              <input
                className="engyne-input"
                type="text"
                value={updateSubject}
                onChange={(event) => setUpdateSubject(event.target.value)}
              />
            </label>
            <label className="engyne-field">
              <span>Message</span>
              <textarea
                className="engyne-input engyne-textarea"
                rows="4"
                value={updateBody}
                onChange={(event) => setUpdateBody(event.target.value)}
              />
            </label>
            <button
              className="engyne-btn engyne-btn--primary"
              onClick={() => handleSend("update")}
              disabled={sending}
            >
              Send update email
            </button>
          </div>
        </div>
        {status && <div className="engyne-alert engyne-alert--warn">{status}</div>}
      </section>

      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Audit trail</div>
            <div className="engyne-card-title">Delivery safeguards</div>
            <div className="engyne-card-helper">
              Every broadcast is logged and verified before sending.
            </div>
          </div>
          <ShieldCheck size={18} className="text-[var(--engyne-muted)]" />
        </div>
        <div className="engyne-muted">
          Email logs will surface here once delivery tracking is enabled.
        </div>
      </section>
    </div>
  );
}
