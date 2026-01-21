// dashboards/client/src/services/api.js

import { getToken } from "./auth";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8001";

/**
 * Generic helper for API calls
 */
async function request(path, options = {}) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...options,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `API error ${res.status}`);
  }

  return res.json();
}

async function requestWithBase(base, path, options = {}) {
  const token = getToken();
  const res = await fetch(`${base}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
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

export async function fetchSlotLeads(slotId, nodeId, limit = 50) {
  const params = new URLSearchParams();
  if (limit) {
    params.set("limit", String(limit));
  }
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/leads?${params.toString()}`);
  }
  return request(`/slots/${slotId}/leads?${params.toString()}`);
}

export async function downloadSlotLeads(slotId, nodeId) {
  const token = getToken();
  const path = nodeId
    ? `/cluster/slots/${nodeId}/${slotId}/leads/download`
    : `/slots/${slotId}/leads/download`;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `API error ${res.status}`);
  }

  return res.blob();
}

/**
 * ---------------------------
 * SLOT CONFIGURATION
 * ---------------------------
 */

export async function fetchSlotConfig(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/config`);
  }
  return request(`/slots/${slotId}/config`);
}

export async function updateSlotConfig(slotId, config, nodeId) {
  const payload = { config };
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/config`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  return request(`/slots/${slotId}/config`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchSlotQuality(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/quality`);
  }
  return request(`/slots/${slotId}/quality`);
}

export async function updateSlotQuality(slotId, payload, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/quality`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  return request(`/slots/${slotId}/quality`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchSlotClientLimits(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/client-limits`);
  }
  return request(`/slots/${slotId}/client-limits`);
}

export async function updateSlotClientLimits(slotId, payload, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/client-limits`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  return request(`/slots/${slotId}/client-limits`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * ---------------------------
 * SLOT COMMANDS
 * ---------------------------
 */

export async function startSlot(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/start`, {
      method: "POST",
    });
  }
  return request(`/slots/${slotId}/start`, {
    method: "POST",
  });
}

export async function stopSlot(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/stop`, {
      method: "POST",
    });
  }
  return request(`/slots/${slotId}/stop`, {
    method: "POST",
  });
}

export async function restartSlot(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/restart`, {
      method: "POST",
    });
  }
  return request(`/slots/${slotId}/restart`, {
    method: "POST",
  });
}

export async function startRemoteLogin(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/remote-login/start`, {
      method: "POST",
    });
  }
  return request(`/slots/${slotId}/remote-login/start`, {
    method: "POST",
  });
}

export async function fetchWhatsAppStatus(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/whatsapp/status`);
  }
  return request(`/slots/${slotId}/whatsapp/status`);
}

export async function connectWhatsApp(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/whatsapp/connect`, {
      method: "POST",
    });
  }
  return request(`/slots/${slotId}/whatsapp/connect`, {
    method: "POST",
  });
}

export async function disconnectWhatsApp(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/whatsapp/disconnect`, {
      method: "POST",
    });
  }
  return request(`/slots/${slotId}/whatsapp/disconnect`, {
    method: "POST",
  });
}

export async function fetchWhatsAppQr(slotId, nodeId) {
  if (nodeId) {
    return request(`/cluster/slots/${nodeId}/${slotId}/whatsapp/qr`);
  }
  return request(`/slots/${slotId}/whatsapp/qr`);
}

export async function finishRemoteLogin(sessionId, apiBase, nodeId) {
  if (apiBase) {
    return requestWithBase(apiBase, `/remote-login/sessions/${sessionId}/finish`, {
      method: "POST",
    });
  }
  if (nodeId) {
    return request(`/cluster/remote-login/${nodeId}/${sessionId}/finish`, {
      method: "POST",
    });
  }
  return request(`/remote-login/sessions/${sessionId}/finish`, {
    method: "POST",
  });
}

/**
 * ---------------------------
 * ADMIN NOTIFICATIONS
 * ---------------------------
 */

export async function sendMaintenanceNotice(payload) {
  return request("/admin/notifications/maintenance", {
    method: "POST",
    body: JSON.stringify(payload || {}),
  });
}

export async function sendUpdateNotice(payload) {
  return request("/admin/notifications/update", {
    method: "POST",
    body: JSON.stringify(payload || {}),
  });
}

/**
 * ---------------------------
 * ADMIN: CLIENT MANAGEMENT
 * ---------------------------
 */

export async function fetchUsers() {
  return request("/admin/users");
}

export async function createUser(payload) {
  return request("/admin/users", {
    method: "POST",
    body: JSON.stringify(payload || {}),
  });
}

export async function updateUserSlots(username, allowedSlots) {
  return request(`/admin/users/${encodeURIComponent(username)}/slots`, {
    method: "POST",
    body: JSON.stringify({ allowed_slots: allowedSlots || [] }),
  });
}

export async function updateUserStatus(username, disabled) {
  return request(`/admin/users/${encodeURIComponent(username)}/status`, {
    method: "POST",
    body: JSON.stringify({ disabled: Boolean(disabled) }),
  });
}

export async function deleteUser(username) {
  return request(`/admin/users/${encodeURIComponent(username)}`, {
    method: "DELETE",
  });
}

export async function sendInvite(payload) {
  return request("/admin/invites", {
    method: "POST",
    body: JSON.stringify(payload || {}),
  });
}
