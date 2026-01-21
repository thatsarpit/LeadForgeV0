import { useEffect, useState } from "react";
import { Download, FileText, Filter, Sparkles } from "lucide-react";
import { useOutletContext } from "react-router-dom";
import { downloadSlotLeads, fetchSlotLeads } from "../../services/api";

export default function ClientLeads() {
  const { slots } = useOutletContext();
  const [selectedSlotId, setSelectedSlotId] = useState("");
  const [status, setStatus] = useState("");
  const [leads, setLeads] = useState([]);
  const [leadsLoading, setLeadsLoading] = useState(false);
  const [leadsError, setLeadsError] = useState("");

  useEffect(() => {
    if (!selectedSlotId && slots.length > 0) {
      setSelectedSlotId(slots[0].slot_id);
    }
  }, [slots, selectedSlotId]);

  const selectedSlot = slots.find((slot) => slot.slot_id === selectedSlotId);

  useEffect(() => {
    if (!selectedSlotId) {
      setLeads([]);
      return;
    }
    let alive = true;
    const loadLeads = async () => {
      setLeadsLoading(true);
      setLeadsError("");
      try {
        const data = await fetchSlotLeads(
          selectedSlotId,
          selectedSlot?.node_id,
          50
        );
        if (!alive) return;
        setLeads(Array.isArray(data.leads) ? data.leads.reverse() : []);
      } catch (err) {
        if (!alive) return;
        setLeadsError("Unable to load recent leads yet.");
      } finally {
        if (alive) setLeadsLoading(false);
      }
    };
    loadLeads();
    return () => {
      alive = false;
    };
  }, [selectedSlotId, selectedSlot?.node_id]);

  const leadLabel = (lead) =>
    lead?.title ||
    lead?.company ||
    lead?.name ||
    lead?.lead_id ||
    lead?.id ||
    lead?.url ||
    "Lead captured";

  const leadStatus = (lead) =>
    lead?.status ||
    lead?.message_status ||
    lead?.verification_status ||
    "captured";

  const handleDownload = async () => {
    if (!selectedSlotId) return;
    setStatus("Preparing download...");
    try {
      const blob = await downloadSlotLeads(selectedSlotId, selectedSlot?.node_id);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${selectedSlotId}_leads.jsonl`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setStatus("Download ready.");
      window.setTimeout(() => setStatus(""), 2000);
    } catch (err) {
      setStatus("Unable to download leads yet.");
      window.setTimeout(() => setStatus(""), 2500);
    }
  };

  return (
    <div className="engyne-page">
      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Lead export</div>
            <div className="engyne-card-title">Download captured leads</div>
            <div className="engyne-card-helper">
              Export JSONL files per slot or by batch once analytics is enabled.
            </div>
          </div>
          <button
            className="engyne-btn engyne-btn--primary"
            onClick={handleDownload}
            disabled={!selectedSlotId}
          >
            <Download size={14} />
            Download
          </button>
        </div>
        <div className="engyne-form-fields">
          <label className="engyne-field">
            <span>Slot</span>
            <select
              className="engyne-input"
              value={selectedSlotId}
              onChange={(event) => setSelectedSlotId(event.target.value)}
            >
              {slots.length === 0 && <option value="">No slots assigned</option>}
              {slots.map((slot) => (
                <option key={slot.slot_id} value={slot.slot_id}>
                  {slot.slot_id} - {slot.node_name || slot.node_id || "local"}
                </option>
              ))}
            </select>
          </label>
          {status && <div className="engyne-muted">{status}</div>}
        </div>
      </section>

      <section className="engyne-panel-soft engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Latest leads</div>
            <div className="engyne-card-title">Recent capture snapshots</div>
            <div className="engyne-card-helper">
              Live feed of the newest leads captured by your slots.
            </div>
          </div>
          <Sparkles size={18} className="text-[var(--engyne-muted)]" />
        </div>
        {leadsLoading && <div className="engyne-muted">Loading recent leads...</div>}
        {leadsError && <div className="engyne-alert engyne-alert--danger">{leadsError}</div>}
        {!leadsLoading && !leadsError && leads.length === 0 && (
          <div className="engyne-empty">No leads captured yet.</div>
        )}
        {!leadsLoading && leads.length > 0 && (
          <div className="engyne-lead-list">
            {leads.slice(0, 12).map((lead, index) => (
              <div key={`${lead.url || lead.id || index}`} className="engyne-lead-row">
                <div>
                  <div className="engyne-lead-title">{leadLabel(lead)}</div>
                  <div className="engyne-lead-meta">
                    {lead.source || "Lead"} · {lead.fetched_at || "Just now"}
                  </div>
                </div>
                <div className="engyne-inline-actions">
                  <span className="engyne-pill">{leadStatus(lead)}</span>
                  {lead.url && (
                    <a
                      className="engyne-btn engyne-btn--ghost engyne-btn--small"
                      href={lead.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr] gap-4">
        <section className="engyne-panel-soft engyne-card">
          <div className="engyne-card-header">
            <div>
              <div className="engyne-kicker">Lead filters</div>
              <div className="engyne-card-title">Refine and triage</div>
              <div className="engyne-card-helper">
                Filter by freshness, lead score, and match accuracy.
              </div>
            </div>
            <Filter size={18} className="text-[var(--engyne-muted)]" />
          </div>
          <div className="engyne-empty">
            Filters will activate after analytics pipelines are connected.
          </div>
        </section>

        <section className="engyne-panel-soft engyne-card">
          <div className="engyne-card-header">
            <div>
              <div className="engyne-kicker">Compliance log</div>
              <div className="engyne-card-title">Audit-ready exports</div>
              <div className="engyne-card-helper">
                Every download is recorded for accountability and quality checks.
              </div>
            </div>
            <FileText size={18} className="text-[var(--engyne-muted)]" />
          </div>
          <div className="engyne-empty">No exports recorded yet.</div>
        </section>
      </div>
    </div>
  );
}
