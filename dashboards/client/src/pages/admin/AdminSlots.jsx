import { useEffect, useMemo, useState } from "react";
import { Pause, Play, RefreshCcw, RotateCcw, Search } from "lucide-react";
import { useOutletContext } from "react-router-dom";

export default function AdminSlots() {
  const { slots, loading, error, actions, refresh } = useOutletContext();
  const [query, setQuery] = useState("");
  const [selectedSlotId, setSelectedSlotId] = useState("");

  const filteredSlots = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return slots;
    return slots.filter((slot) =>
      `${slot.slot_id} ${slot.node_id} ${slot.node_name}`.toLowerCase().includes(term)
    );
  }, [slots, query]);

  useEffect(() => {
    if (!selectedSlotId && slots.length > 0) {
      setSelectedSlotId(slots[0].slot_id);
    }
  }, [slots, selectedSlotId]);

  useEffect(() => {
    if (!selectedSlotId || filteredSlots.length === 0) return;
    const stillVisible = filteredSlots.some((slot) => slot.slot_id === selectedSlotId);
    if (!stillVisible) {
      setSelectedSlotId(filteredSlots[0]?.slot_id || "");
    }
  }, [filteredSlots, selectedSlotId]);

  const selectedSlot = useMemo(
    () => slots.find((slot) => slot.slot_id === selectedSlotId) || slots[0],
    [slots, selectedSlotId]
  );

  return (
    <div className="engyne-page">
      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Slot operations</div>
            <div className="engyne-card-title">Fleet control center</div>
            <div className="engyne-card-helper">
              Monitor slot health and resolve issues across nodes.
            </div>
          </div>
          <div className="engyne-inline-actions">
            <div className="engyne-search">
              <Search size={14} />
              <input
                className="engyne-search-input"
                placeholder="Search slots"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <button className="engyne-btn engyne-btn--ghost engyne-btn--small" onClick={refresh}>
              <RefreshCcw size={14} />
              Refresh
            </button>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-4">
        <section className="engyne-panel-soft engyne-card engyne-slot-list">
          {loading && <div className="engyne-muted">Loading slots...</div>}
          {error && <div className="engyne-alert engyne-alert--danger">{error}</div>}

          {!loading && filteredSlots.length === 0 && (
            <div className="engyne-empty">No slots match your search.</div>
          )}

          <div className="engyne-slot-stack">
            {filteredSlots.map((slot) => {
              const isActive = selectedSlot?.slot_id === slot.slot_id;
              const isRunning = slot.status === "RUNNING";
              return (
                <button
                  key={slot.slot_id}
                  className={`engyne-slot-row ${isActive ? "is-active" : ""}`}
                  onClick={() => setSelectedSlotId(slot.slot_id)}
                >
                  <div>
                    <div className="engyne-slot-title">{slot.slot_id}</div>
                    <div className="engyne-slot-meta">
                      {slot.node_name || slot.node_id || "local"} - {slot.status || "-"}
                    </div>
                  </div>
                  <div className="engyne-slot-actions">
                    <span className={`engyne-pill ${isRunning ? "engyne-pill--good" : ""}`}>
                      {isRunning ? "running" : "stopped"}
                    </span>
                    {isRunning ? (
                      <button
                        className="engyne-btn engyne-btn--ghost engyne-btn--small"
                        onClick={(event) => {
                          event.stopPropagation();
                          actions.stop(slot);
                        }}
                      >
                        <Pause size={14} />
                        Pause
                      </button>
                    ) : (
                      <button
                        className="engyne-btn engyne-btn--primary engyne-btn--small"
                        onClick={(event) => {
                          event.stopPropagation();
                          actions.start(slot);
                        }}
                      >
                        <Play size={14} />
                        Start
                      </button>
                    )}
                    <button
                      className="engyne-btn engyne-btn--ghost engyne-btn--small"
                      onClick={(event) => {
                        event.stopPropagation();
                        actions.restart(slot);
                      }}
                    >
                      <RotateCcw size={14} />
                      Restart
                    </button>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <section className="engyne-panel engyne-card">
          <div className="engyne-card-header">
            <div>
              <div className="engyne-kicker">Slot details</div>
              <div className="engyne-card-title">
                {selectedSlot ? selectedSlot.slot_id : "Select a slot"}
              </div>
              <div className="engyne-card-helper">
                {selectedSlot
                  ? `${selectedSlot.node_name || selectedSlot.node_id || "local"} - ${
                      selectedSlot.status || "-"
                    }`
                  : "Pick a slot to view metrics."}
              </div>
            </div>
          </div>
          {selectedSlot ? (
            <div className="engyne-slot-detail-grid">
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Throughput</div>
                <div className="engyne-detail-value">
                  {Math.round(Number(selectedSlot.metrics?.throughput || 0))}/m
                </div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Leads parsed</div>
                <div className="engyne-detail-value">
                  {(() => {
                    const total = Number(selectedSlot.metrics?.leads_parsed || 0);
                    const baseline = Number(selectedSlot.run_leads_start || 0);
                    return Math.max(0, total - baseline);
                  })()}
                </div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Errors</div>
                <div className="engyne-detail-value">
                  {selectedSlot.metrics?.last_error ? "Recent" : "None"}
                </div>
              </div>
            </div>
          ) : (
            <div className="engyne-empty">No slot selected.</div>
          )}
        </section>
      </div>
    </div>
  );
}
