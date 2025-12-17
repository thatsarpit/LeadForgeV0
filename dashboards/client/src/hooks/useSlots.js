import { useEffect, useRef, useState } from "react";
import {
  fetchSlots,
  startSlot,
  stopSlot,
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

  const loadSlots = async () => {
    try {
      const data = await fetchSlots();
      setSlots(data.slots || []);
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

  const handleAction = async (slotId, action) => {
    markBusy(slotId);

    try {
      if (action === "start") await startSlot(slotId);
      if (action === "stop") await stopSlot(slotId);
      if (action === "restart") await restartSlot(slotId);

      await loadSlots(); // backend reconciliation
    } catch (err) {
      console.error(`[useSlots] action failed: ${action}`, err);
      clearBusy(slotId);
    }
  };

  return {
    slots,
    loading,
    error,
    refresh: loadSlots,
    actions: {
      start: (id) => handleAction(id, "start"),
      stop: (id) => handleAction(id, "stop"),
      restart: (id) => handleAction(id, "restart"),
    },
  };
}