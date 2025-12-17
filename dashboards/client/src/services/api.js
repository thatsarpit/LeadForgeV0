// dashboards/client/src/services/api.js

const API_BASE = "http://127.0.0.1:8000";

/**
 * Generic helper for API calls
 */
async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `API error ${res.status}`);
  }

  return res.json();
}

/**
 * ---------------------------
 * SLOT READ (OBSERVER)
 * ---------------------------
 */

/**
 * Get all slots
 */
export async function fetchSlots() {
  return request("/slots");
}

/**
 * Get single slot status (optional, future use)
 */
export async function fetchSlot(slotId) {
  return request(`/slots/${slotId}`);
}

/**
 * ---------------------------
 * SLOT COMMANDS
 * ---------------------------
 */

export async function startSlot(slotId) {
  return request(`/slots/${slotId}/start`, {
    method: "POST",
  });
}

export async function stopSlot(slotId) {
  return request(`/slots/${slotId}/stop`, {
    method: "POST",
  });
}

export async function restartSlot(slotId) {
  return request(`/slots/${slotId}/restart`, {
    method: "POST",
  });
}