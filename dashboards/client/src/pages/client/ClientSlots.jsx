import { useEffect, useMemo, useState } from "react";
import { Monitor, Pause, Play, RefreshCcw, RotateCcw, Save, Search } from "lucide-react";
import { useOutletContext } from "react-router-dom";
import {
  fetchSlotClientLimits,
  fetchSlotConfig,
  fetchSlotLoginStatus,
  fetchSlotQuality,
  updateSlotClientLimits,
  updateSlotConfig,
  updateSlotQuality,
} from "../../services/api";
import { COUNTRY_ALIAS_OVERRIDES, COUNTRY_OPTIONS } from "../../services/countries.js";

const DEFAULT_PREFS = {
  leadTargetEnabled: false,
  leadTarget: 120,
  keywords: "",
  exclusions: "",
  countries: [],
  maxLeadAgeSeconds: 30,
  zeroSecondOnly: false,
  allowUnknownAge: false,
  requireMobileAvailable: false,
  requireMobileVerified: false,
  requireEmailAvailable: false,
  requireEmailVerified: false,
  requireWhatsAppAvailable: false,
  qualityBias: 50,
  minMemberMonths: 0,
  maxAgeHours: 48,
};

const normalizeToken = (value) =>
  String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");

const countrySynonyms = (country) => {
  const base = [country.code, country.name];
  const overrides = COUNTRY_ALIAS_OVERRIDES[country.code] || [];
  const normalized = [...base, ...overrides].map(normalizeToken);
  return Array.from(new Set(normalized));
};

const resolveSelectedCountries = (config) => {
  if (Array.isArray(config?.client_regions) && config.client_regions.length) {
    return config.client_regions.filter((code) =>
      COUNTRY_OPTIONS.some((country) => country.code === code)
    );
  }
  const raw = config?.country;
  if (!raw) return [];
  const tokens = Array.isArray(raw) ? raw : String(raw).split(/,|\n/);
  const normalizedTokens = tokens.map(normalizeToken);
  return COUNTRY_OPTIONS.filter((country) =>
    countrySynonyms(country).some((alias) => normalizedTokens.includes(alias))
  ).map((country) => country.code);
};

const expandCountrySelection = (codes) => {
  const synonyms = [];
  codes.forEach((code) => {
    const country = COUNTRY_OPTIONS.find((entry) => entry.code === code);
    if (country) {
      synonyms.push(...countrySynonyms(country));
    }
  });
  return Array.from(new Set(synonyms));
};

export default function ClientSlots() {
  const { slots, loading, error, actions, refresh } = useOutletContext();
  const [query, setQuery] = useState("");
  const [selectedSlotId, setSelectedSlotId] = useState("");
  const [formState, setFormState] = useState(DEFAULT_PREFS);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveState, setSaveState] = useState("");
  const [countrySearch, setCountrySearch] = useState("");
  const [loginStatus, setLoginStatus] = useState(null);
  const [loginStatusLoading, setLoginStatusLoading] = useState(false);
  const [loginStatusError, setLoginStatusError] = useState("");

  useEffect(() => {
    if (!selectedSlotId && slots.length > 0) {
      setSelectedSlotId(slots[0].slot_id);
    }
  }, [slots, selectedSlotId]);

  const filteredSlots = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return slots;
    return slots.filter((slot) =>
      `${slot.slot_id} ${slot.node_id} ${slot.node_name}`.toLowerCase().includes(term)
    );
  }, [slots, query]);

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

  const filteredCountries = useMemo(() => {
    const term = normalizeToken(countrySearch);
    if (!term) return COUNTRY_OPTIONS;
    return COUNTRY_OPTIONS.filter((country) => {
      const pool = [country.code, country.name].map(normalizeToken);
      return pool.some((value) => value.includes(term));
    });
  }, [countrySearch]);

  const fieldsDisabled = !selectedSlot || configLoading;

  useEffect(() => {
    if (!selectedSlot) return;
    let alive = true;

    const loadConfig = async () => {
      setConfigLoading(true);
      setConfigError("");
      const nodeId = selectedSlot.node_id;

      const [limitsResult, qualityResult, configResult] = await Promise.allSettled([
        fetchSlotClientLimits(selectedSlot.slot_id, nodeId),
        fetchSlotQuality(selectedSlot.slot_id, nodeId),
        fetchSlotConfig(selectedSlot.slot_id, nodeId),
      ]);

      if (!alive) return;

      const limits = limitsResult.status === "fulfilled" ? limitsResult.value : {};
      const quality = qualityResult.status === "fulfilled" ? qualityResult.value : {};
      const config = configResult.status === "fulfilled" ? configResult.value?.config || {} : {};

      const maxClicks = Number(limits.max_verified_leads_per_cycle ?? 0);
      const leadTargetEnabled = maxClicks > 0;
      const keywords = Array.isArray(config.search_terms)
        ? config.search_terms.join("\n")
        : typeof config.search_terms === "string"
          ? config.search_terms
          : "";
      const exclusions = Array.isArray(config.exclude_terms)
        ? config.exclude_terms.join("\n")
        : typeof config.exclude_terms === "string"
          ? config.exclude_terms
          : "";

        setFormState({
          leadTargetEnabled,
          leadTarget: leadTargetEnabled ? maxClicks : DEFAULT_PREFS.leadTarget,
          keywords,
          exclusions,
          countries: resolveSelectedCountries(config),
          maxLeadAgeSeconds: 30,
          zeroSecondOnly: false,
          allowUnknownAge: false,
          requireMobileAvailable: Boolean(config.require_mobile_available),
          requireMobileVerified: Boolean(config.require_mobile_verified),
          requireEmailAvailable: Boolean(config.require_email_available),
          requireEmailVerified: Boolean(config.require_email_verified),
          requireWhatsAppAvailable: Boolean(config.require_whatsapp_available),
          qualityBias: Number(quality.quality_level ?? DEFAULT_PREFS.qualityBias),
          minMemberMonths: Number(quality.min_member_months ?? 0),
          maxAgeHours: Number(quality.max_age_hours ?? 48),
      });

      if (
        limitsResult.status === "rejected" ||
        qualityResult.status === "rejected" ||
        configResult.status === "rejected"
      ) {
        setConfigError("Some slot settings could not be loaded.");
      }

      setConfigLoading(false);
    };

    loadConfig();

    return () => {
      alive = false;
    };
  }, [selectedSlot?.slot_id, selectedSlot?.node_id]);

  const refreshLoginStatus = async () => {
    if (!selectedSlot) return;
    setLoginStatusLoading(true);
    setLoginStatusError("");
    try {
      const status = await fetchSlotLoginStatus(selectedSlot.slot_id, selectedSlot.node_id);
      setLoginStatus(status);
    } catch (err) {
      setLoginStatusError("Unable to check IndiaMart login.");
    } finally {
      setLoginStatusLoading(false);
    }
  };

  useEffect(() => {
    if (!selectedSlot) {
      setLoginStatus(null);
      setLoginStatusError("");
      setLoginStatusLoading(false);
      return;
    }
    refreshLoginStatus();
  }, [selectedSlot?.slot_id, selectedSlot?.node_id]);

  const updatePref = (field, value) => {
    setFormState((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const togglePref = (field) => {
    setFormState((prev) => ({
      ...prev,
      [field]: !prev[field],
    }));
  };

  const parseList = (value) =>
    value
      .split(/\n|,/)
      .map((item) => item.trim())
      .filter(Boolean);

  const toggleListItem = (list, value) => {
    if (list.includes(value)) {
      return list.filter((item) => item !== value);
    }
    return [...list, value];
  };

  const savePrefs = async () => {
    if (!selectedSlot) return;
    setSaving(true);
    setSaveState("");
    setConfigError("");
    const nodeId = selectedSlot.node_id;

    const limitsPayload = {
      max_verified_leads_per_cycle: formState.leadTargetEnabled
        ? Number(formState.leadTarget || 0)
        : 0,
      max_run_minutes: 0,
    };

    const qualityPayload = {
      quality_level: Number(formState.qualityBias || 0),
      min_member_months: Number(formState.minMemberMonths || 0),
      max_age_hours: Number(formState.maxAgeHours || 48),
      max_verified_leads_per_cycle: Number(formState.leadTarget || 0),
    };

    const configPayload = {
      search_terms: parseList(formState.keywords || ""),
      exclude_terms: parseList(formState.exclusions || ""),
      country: expandCountrySelection(formState.countries || []),
      client_regions: formState.countries || [],
      max_lead_age_seconds: 30,
      zero_second_only: false,
      allow_unknown_age: false,
      require_mobile_available: Boolean(formState.requireMobileAvailable),
      require_mobile_verified: Boolean(formState.requireMobileVerified),
      require_email_available: Boolean(formState.requireEmailAvailable),
      require_email_verified: Boolean(formState.requireEmailVerified),
      require_whatsapp_available: Boolean(formState.requireWhatsAppAvailable),
    };

    try {
      await Promise.all([
        updateSlotClientLimits(selectedSlot.slot_id, limitsPayload, nodeId),
        updateSlotQuality(selectedSlot.slot_id, qualityPayload, nodeId),
        updateSlotConfig(selectedSlot.slot_id, configPayload, nodeId),
      ]);
      setSaveState("Saved");
      window.setTimeout(() => setSaveState(""), 2000);
    } catch (err) {
      setConfigError("Failed to save slot configuration.");
    } finally {
      setSaving(false);
    }
  };

  const handleRemoteLogin = () => {
    if (!selectedSlot) return;
    const params = new URLSearchParams({
      slot: selectedSlot.slot_id,
      node: selectedSlot.node_id || "local",
    });
    window.open(`/remote-login?${params.toString()}`, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="engyne-page">
      <section className="engyne-panel engyne-card">
        <div className="engyne-card-header">
          <div>
            <div className="engyne-kicker">Slot directory</div>
            <div className="engyne-card-title">Manage all assigned slots</div>
            <div className="engyne-card-helper">Search, start, and tune each slot.</div>
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

      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-4 min-h-0">
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
                          actions.pause(slot);
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
                  ? `${selectedSlot.node_name || selectedSlot.node_id || "local"} - ${selectedSlot.status || "-"
                  }`
                  : "Choose a slot to view controls."}
              </div>
            </div>
            <div className="engyne-inline-actions">
              <button
                className="engyne-btn engyne-btn--ghost engyne-btn--small"
                onClick={refreshLoginStatus}
                disabled={!selectedSlot || loginStatusLoading}
              >
                <RefreshCcw size={14} />
                Check login
              </button>
              <button
                className="engyne-btn engyne-btn--ghost engyne-btn--small"
                onClick={handleRemoteLogin}
                disabled={!selectedSlot}
              >
                <Monitor size={14} />
                Remote login
              </button>
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
                    const runStart = Number(selectedSlot.run_leads_start || 0);
                    const delta = Math.max(0, total - runStart);
                    return delta;
                  })()}
                </div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Clicks / Verified (run)</div>
                <div className="engyne-detail-value">
                  {(() => {
                    const clicked =
                      Number(selectedSlot.metrics?.clicked_total || 0) -
                      Number(selectedSlot.run_clicked_start || 0);
                    const verified =
                      Number(selectedSlot.metrics?.verified_total || 0) -
                      Number(selectedSlot.run_verified_start || 0);
                    const safeClicked = Math.max(0, clicked);
                    const safeVerified = Math.max(0, verified);
                    return `${safeClicked}/${safeVerified}`;
                  })()}
                </div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Status</div>
                <div className="engyne-detail-value">{selectedSlot.status || "UNKNOWN"}</div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Stop reason</div>
                <div className="engyne-detail-value">{selectedSlot.stop_reason || "—"}</div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Last exit code</div>
                <div className="engyne-detail-value">
                  {selectedSlot.last_exit_code !== undefined && selectedSlot.last_exit_code !== null
                    ? selectedSlot.last_exit_code
                    : "—"}
                </div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Heartbeat</div>
                <div className="engyne-detail-value">
                  {selectedSlot.last_heartbeat ? "Live" : "None"}
                </div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">IndiaMart login</div>
                <div className="engyne-detail-value">
                  {loginStatusLoading
                    ? "Checking..."
                    : loginStatus?.status === "logged_in"
                      ? "Logged in"
                      : loginStatus?.status === "logged_out"
                        ? "Login required"
                        : "Unknown"}
                </div>
                {loginStatus?.checked_at && (
                  <div className="engyne-detail-label">
                    Checked {new Date(loginStatus.checked_at).toLocaleString()}
                  </div>
                )}
                {loginStatusError && (
                  <div className="engyne-alert engyne-alert--danger">{loginStatusError}</div>
                )}
              </div>
            </div>
          ) : (
            <div className="engyne-empty">No slot selected.</div>
          )}

          {configLoading && <div className="engyne-muted">Loading slot settings...</div>}
          {configError && <div className="engyne-alert engyne-alert--danger">{configError}</div>}

          <div className="engyne-divider" />

          <div className="engyne-form-grid">
            <div>
              <div className="engyne-kicker">Scheduler</div>
              <div className="engyne-muted">
                Enable the caps you want enforced for each run window.
              </div>
            </div>
            <div className="engyne-form-fields">
              <div className="engyne-toggle-list">
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("leadTargetEnabled")}
                  disabled={fieldsDisabled}
                >
                  <span>Lead target cap</span>
                  <span
                    className={
                      formState.leadTargetEnabled ? "engyne-toggle-pill is-on" : "engyne-toggle-pill"
                    }
                  >
                    {formState.leadTargetEnabled ? "On" : "Off"}
                  </span>
                </button>
              </div>
              <label className="engyne-field">
                <span>Max verified leads per cycle</span>
                <input
                  className="engyne-input"
                  type="number"
                  min="0"
                  value={formState.leadTarget}
                  onChange={(event) => updatePref("leadTarget", Number(event.target.value))}
                  disabled={fieldsDisabled || !formState.leadTargetEnabled}
                />
              </label>
            </div>
          </div>

          <div className="engyne-divider" />

          <div className="engyne-form-grid">
            <div>
              <div className="engyne-kicker">Filters & keywords</div>
              <div className="engyne-muted">
                Control what the slot targets and excludes.
              </div>
            </div>
            <div className="engyne-form-fields">
              <div className="engyne-muted">
                Lead age is fixed to ≤ 30 seconds; unknown ages are ignored. Only mobile/email/WhatsApp requirements remain configurable below.
              </div>
              <div className="engyne-toggle-list">
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("requireMobileAvailable")}
                  disabled={fieldsDisabled}
                >
                  <span>Require mobile available</span>
                  <span
                    className={
                      formState.requireMobileAvailable
                        ? "engyne-toggle-pill is-on"
                        : "engyne-toggle-pill"
                    }
                  >
                    {formState.requireMobileAvailable ? "On" : "Off"}
                  </span>
                </button>
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("requireMobileVerified")}
                  disabled={fieldsDisabled}
                >
                  <span>Require mobile verified</span>
                  <span
                    className={
                      formState.requireMobileVerified
                        ? "engyne-toggle-pill is-on"
                        : "engyne-toggle-pill"
                    }
                  >
                    {formState.requireMobileVerified ? "On" : "Off"}
                  </span>
                </button>
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("requireEmailAvailable")}
                  disabled={fieldsDisabled}
                >
                  <span>Require email available</span>
                  <span
                    className={
                      formState.requireEmailAvailable
                        ? "engyne-toggle-pill is-on"
                        : "engyne-toggle-pill"
                    }
                  >
                    {formState.requireEmailAvailable ? "On" : "Off"}
                  </span>
                </button>
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("requireEmailVerified")}
                  disabled={fieldsDisabled}
                >
                  <span>Require email verified</span>
                  <span
                    className={
                      formState.requireEmailVerified
                        ? "engyne-toggle-pill is-on"
                        : "engyne-toggle-pill"
                    }
                  >
                    {formState.requireEmailVerified ? "On" : "Off"}
                  </span>
                </button>
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("requireWhatsAppAvailable")}
                  disabled={fieldsDisabled}
                >
                  <span>Require WhatsApp available</span>
                  <span
                    className={
                      formState.requireWhatsAppAvailable
                        ? "engyne-toggle-pill is-on"
                        : "engyne-toggle-pill"
                    }
                  >
                    {formState.requireWhatsAppAvailable ? "On" : "Off"}
                  </span>
                </button>
              </div>
              <div className="engyne-muted">
                Contact availability is derived from Buyer Details &rarr; Available icons (tooltip text
                like “Mobile Number is Verified”, “Email ID Available”, “WhatsApp Available”).
              </div>
              <label className="engyne-field">
                <span>Keywords</span>
                <textarea
                  className="engyne-input engyne-textarea"
                  rows="3"
                  value={formState.keywords}
                  onChange={(event) => updatePref("keywords", event.target.value)}
                  disabled={fieldsDisabled}
                />
              </label>
              <label className="engyne-field">
                <span>Exclusions</span>
                <textarea
                  className="engyne-input engyne-textarea"
                  rows="2"
                  value={formState.exclusions}
                  onChange={(event) => updatePref("exclusions", event.target.value)}
                  disabled={fieldsDisabled}
                />
              </label>
              <div className="engyne-field">
                <span>Countries</span>
                <input
                  className="engyne-input"
                  type="text"
                  placeholder="Search countries"
                  value={countrySearch}
                  onChange={(event) => setCountrySearch(event.target.value)}
                  disabled={fieldsDisabled}
                />
                <div className="engyne-inline-actions">
                  <button
                    className="engyne-btn engyne-btn--ghost engyne-btn--small"
                    type="button"
                    disabled={fieldsDisabled}
                    onClick={() => updatePref("countries", COUNTRY_OPTIONS.map((c) => c.code))}
                  >
                    Select all
                  </button>
                  <button
                    className="engyne-btn engyne-btn--ghost engyne-btn--small"
                    type="button"
                    disabled={fieldsDisabled}
                    onClick={() => updatePref("countries", [])}
                  >
                    Clear
                  </button>
                </div>
                <div className="engyne-checklist engyne-checklist--scroll">
                  {filteredCountries.map((country) => (
                    <label key={country.code} className="engyne-check">
                      <input
                        type="checkbox"
                        disabled={fieldsDisabled}
                        checked={formState.countries.includes(country.code)}
                        onChange={() =>
                          updatePref(
                            "countries",
                            toggleListItem(formState.countries, country.code)
                          )
                        }
                      />
                      <span>{country.name}</span>
                    </label>
                  ))}
                </div>
              </div>
              <label className="engyne-field">
                <span>Quality vs quantity</span>
                <input
                  className="engyne-range"
                  type="range"
                  min="0"
                  max="100"
                  value={formState.qualityBias}
                  onChange={(event) => updatePref("qualityBias", Number(event.target.value))}
                  disabled={fieldsDisabled}
                />
                <div className="engyne-range-labels">
                  <span>More leads</span>
                  <span>Higher quality</span>
                </div>
              </label>
            </div>
          </div>

          <div className="engyne-divider" />

          <div className="engyne-inline-actions">
            <button
              className="engyne-btn engyne-btn--primary"
              onClick={savePrefs}
              disabled={!selectedSlot || configLoading || saving}
            >
              <Save size={14} />
              {saving ? "Saving..." : "Save configuration"}
            </button>
            {saveState && <span className="engyne-muted">{saveState}</span>}
          </div>
        </section>
      </div>
    </div>
  );
}
