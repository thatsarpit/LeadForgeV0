import { useEffect, useRef, useState } from "react";
import {
  fetchSlots,
  startSlot,
  stopSlot,
  pauseSlot,
  restartSlot,
} from "../services/api";

/**
 * useSlots
 * Single source of truth for slot state + actions
 * Handles polling, optimistic busy state, and reconciliation
 */
export default function useSlots({ pollInterval = 3000 } = {}) {
  const [slots, setSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const pollRef = useRef(null);

  const resolveSlot = (slotOrId, nodeId) => {
    if (slotOrId && typeof slotOrId === "object") {
      return {
        id: slotOrId.slot_id || slotOrId.id,
        nodeId: slotOrId.node_id,
      };
    }
    return { id: slotOrId, nodeId };
  };

  const loadSlots = async () => {
    try {
      const data = await fetchSlots();
      const filtered = (data.slots || []).filter((slot) => {
        const raw = String(slot.slot_id || slot.id || "");
        const slotId = raw.includes("::") ? raw.split("::").pop() : raw;
        return slotId && !slotId.startsWith("_");
      });
      setSlots(filtered);
      setError(null);
    } catch (err) {
      console.error("[useSlots] fetch failed", err);
      setError("Failed to fetch slots");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSlots();

    pollRef.current = setInterval(loadSlots, pollInterval);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [pollInterval]);

  const markBusy = (slotId) => {
    setSlots((prev) =>
      prev.map((s) =>
        s.slot_id === slotId ? { ...s, busy: true } : s
      )
    );
  };

  const clearBusy = (slotId) => {
    setSlots((prev) =>
      prev.map((s) =>
        s.slot_id === slotId ? { ...s, busy: false } : s
      )
    );
  };

  const handleAction = async (slotOrId, action, nodeId) => {
    const resolved = resolveSlot(slotOrId, nodeId);
    if (!resolved.id) return;
    markBusy(resolved.id);

    try {
      if (action === "start") await startSlot(resolved.id, resolved.nodeId);
      if (action === "stop") await stopSlot(resolved.id, resolved.nodeId);
      if (action === "pause") await pauseSlot(resolved.id, resolved.nodeId);
      if (action === "restart") await restartSlot(resolved.id, resolved.nodeId);

      await loadSlots(); // backend reconciliation
    } catch (err) {
      console.error(`[useSlots] action failed: ${action}`, err);
      clearBusy(resolved.id);
    }
  };

  return {
    slots,
    loading,
    error,
    refresh: loadSlots,
    actions: {
      start: (slotOrId, nodeId) => handleAction(slotOrId, "start", nodeId),
      stop: (slotOrId, nodeId) => handleAction(slotOrId, "stop", nodeId),
      pause: (slotOrId, nodeId) => handleAction(slotOrId, "pause", nodeId),
      restart: (slotOrId, nodeId) => handleAction(slotOrId, "restart", nodeId),
    },
  };
}
