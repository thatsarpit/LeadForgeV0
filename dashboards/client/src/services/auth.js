const TOKEN_KEY = "lf_token";
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8001";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export async function fetchMe(token) {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    throw new Error("Failed to load user");
  }
  return res.json();
}

export function getGoogleLoginUrl(redirectUrl) {
  const target = redirectUrl || window.location.origin;
  const encoded = encodeURIComponent(target);
  return `${API_BASE}/auth/google/start?redirect=${encoded}`;
}

export async function loginWithDemoCode(code) {
  const res = await fetch(`${API_BASE}/auth/demo`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Invalid demo code");
  }
  return res.json();
}

export async function updateOnboardingComplete(complete = true) {
  const token = getToken();
  if (!token) {
    throw new Error("Missing token");
  }
  const res = await fetch(`${API_BASE}/auth/onboarding`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ complete }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Failed to update onboarding");
  }
  return res.json();
}
