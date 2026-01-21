import { useEffect, useMemo, useState } from "react";
import { Monitor, Pause, Play, RefreshCcw, RotateCcw, Save, Search } from "lucide-react";
import { useOutletContext } from "react-router-dom";
import {
  fetchSlotClientLimits,
  fetchSlotConfig,
  fetchSlotQuality,
  fetchWhatsAppQr,
  fetchWhatsAppStatus,
  connectWhatsApp,
  disconnectWhatsApp,
  updateSlotClientLimits,
  updateSlotConfig,
  updateSlotQuality,
} from "../../services/api";
import { COUNTRY_ALIAS_OVERRIDES, COUNTRY_OPTIONS } from "../../data/countries";

const LOCAL_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

const DEFAULT_PREFS = {
  leadTargetEnabled: false,
  maxRuntimeEnabled: false,
  windowEnabled: false,
  leadTarget: 120,
  maxRuntime: 2,
  windowStart: "09:00",
  windowEnd: "18:00",
  days: ["mon", "tue", "wed", "thu", "fri"],
  timezone: LOCAL_TZ,
  keywords: "",
  exclusions: "",
  countries: [],
  qualityBias: 50,
  whatsappEnabled: false,
  whatsappSession: "",
  whatsappTemplate: "",
  whatsappMaxPerHour: 20,
  whatsappMinDelay: 25,
  whatsappStopOnReply: false,
  indiamartMessageEnabled: false,
  indiamartMessageTemplate: "",
  indiamartMessageMaxPerDay: 20,
  indiamartMessageMinDelay: 30,
};

const TIMEZONES =
  typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone")
    : [LOCAL_TZ];

const DAY_OPTIONS = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
  { key: "sat", label: "Sat" },
  { key: "sun", label: "Sun" },
];

const DAY_ALIASES = {
  mon: "mon",
  monday: "mon",
  tue: "tue",
  tues: "tue",
  tuesday: "tue",
  wed: "wed",
  weds: "wed",
  wednesday: "wed",
  thu: "thu",
  thur: "thu",
  thurs: "thu",
  thursday: "thu",
  fri: "fri",
  friday: "fri",
  sat: "sat",
  saturday: "sat",
  sun: "sun",
  sunday: "sun",
};

const normalizeToken = (value) =>
  String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");

const resolveDays = (value) => {
  if (!value) return DEFAULT_PREFS.days;
  const tokens = Array.isArray(value) ? value : String(value).split(/,|\s/);
  const normalized = tokens
    .map((token) => DAY_ALIASES[String(token).toLowerCase().trim()])
    .filter(Boolean);
  return normalized.length ? Array.from(new Set(normalized)) : DEFAULT_PREFS.days;
};

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
  const [whatsappStatus, setWhatsAppStatus] = useState(null);
  const [whatsappQr, setWhatsAppQr] = useState("");
  const [whatsappLoading, setWhatsAppLoading] = useState(false);
  const [whatsappError, setWhatsAppError] = useState("");

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

      const maxClicks = Number(limits.max_clicks_per_run ?? 0);
      const maxRunMinutes = Number(limits.max_run_minutes ?? 0);
      const leadTargetEnabled = maxClicks > 0;
      const maxRuntimeEnabled = maxRunMinutes > 0;
      const schedule = config.client_schedule || {};
      const windowEnabled =
        typeof schedule.enabled === "boolean"
          ? schedule.enabled
          : Boolean(schedule.window_start || schedule.window_end);
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
        maxRuntimeEnabled,
        windowEnabled,
        leadTarget: leadTargetEnabled ? maxClicks : DEFAULT_PREFS.leadTarget,
        maxRuntime: maxRuntimeEnabled
          ? Math.round((maxRunMinutes / 60) * 10) / 10
          : DEFAULT_PREFS.maxRuntime,
        windowStart: schedule.window_start || DEFAULT_PREFS.windowStart,
        windowEnd: schedule.window_end || DEFAULT_PREFS.windowEnd,
        days: resolveDays(schedule.days),
        timezone: schedule.timezone || DEFAULT_PREFS.timezone,
        keywords,
        exclusions,
        countries: resolveSelectedCountries(config),
        qualityBias: Number(quality.quality_level ?? DEFAULT_PREFS.qualityBias),
        whatsappEnabled: Boolean(config.whatsapp_enabled),
        whatsappSession: String(config.whatsapp_waha_session || ""),
        whatsappTemplate: String(config.whatsapp_template || ""),
        whatsappMaxPerHour: Number(config.whatsapp_max_per_hour ?? DEFAULT_PREFS.whatsappMaxPerHour),
        whatsappMinDelay: Number(config.whatsapp_min_delay_s ?? DEFAULT_PREFS.whatsappMinDelay),
        whatsappStopOnReply: Boolean(config.whatsapp_stop_on_reply),
        indiamartMessageEnabled: Boolean(config.indiamart_message_enabled),
        indiamartMessageTemplate: String(config.indiamart_message_template || ""),
        indiamartMessageMaxPerDay: Number(
          config.indiamart_message_max_per_day ?? DEFAULT_PREFS.indiamartMessageMaxPerDay
        ),
        indiamartMessageMinDelay: Number(
          config.indiamart_message_min_delay_s ?? DEFAULT_PREFS.indiamartMessageMinDelay
        ),
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

  useEffect(() => {
    if (!selectedSlot) {
      setWhatsAppStatus(null);
      setWhatsAppQr("");
      setWhatsAppError("");
      return;
    }
    let alive = true;
    const loadWhatsApp = async () => {
      setWhatsAppLoading(true);
      setWhatsAppError("");
      try {
        const status = await fetchWhatsAppStatus(selectedSlot.slot_id, selectedSlot.node_id);
        if (!alive) return;
        setWhatsAppStatus(status);
      } catch (err) {
        if (!alive) return;
        setWhatsAppError("WhatsApp service is not reachable yet.");
      } finally {
        if (alive) setWhatsAppLoading(false);
      }
    };
    loadWhatsApp();
    return () => {
      alive = false;
    };
  }, [selectedSlot?.slot_id, selectedSlot?.node_id]);

  const handleWhatsAppConnect = async () => {
    if (!selectedSlot) return;
    setWhatsAppLoading(true);
    setWhatsAppError("");
    try {
      await connectWhatsApp(selectedSlot.slot_id, selectedSlot.node_id);
      const qr = await fetchWhatsAppQr(selectedSlot.slot_id, selectedSlot.node_id);
      setWhatsAppQr(normalizeQr(qr.qr || ""));
      const status = await fetchWhatsAppStatus(selectedSlot.slot_id, selectedSlot.node_id);
      setWhatsAppStatus(status);
    } catch (err) {
      setWhatsAppError("Unable to start WhatsApp session.");
    } finally {
      setWhatsAppLoading(false);
    }
  };

  const handleWhatsAppDisconnect = async () => {
    if (!selectedSlot) return;
    setWhatsAppLoading(true);
    setWhatsAppError("");
    try {
      await disconnectWhatsApp(selectedSlot.slot_id, selectedSlot.node_id);
      setWhatsAppStatus(null);
      setWhatsAppQr("");
    } catch (err) {
      setWhatsAppError("Unable to disconnect WhatsApp session.");
    } finally {
      setWhatsAppLoading(false);
    }
  };

  const handleWhatsAppQr = async () => {
    if (!selectedSlot) return;
    setWhatsAppLoading(true);
    setWhatsAppError("");
    try {
      const qr = await fetchWhatsAppQr(selectedSlot.slot_id, selectedSlot.node_id);
      setWhatsAppQr(normalizeQr(qr.qr || ""));
    } catch (err) {
      setWhatsAppError("QR not available yet.");
    } finally {
      setWhatsAppLoading(false);
    }
  };

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

  const normalizeQr = (qr) => {
    if (!qr) return "";
    if (qr.startsWith("data:image") || qr.startsWith("http")) {
      return qr;
    }
    return `data:image/png;base64,${qr}`;
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
      max_clicks_per_run: formState.leadTargetEnabled
        ? Number(formState.leadTarget || 0)
        : 0,
      max_run_minutes: formState.maxRuntimeEnabled
        ? Math.round(Number(formState.maxRuntime || 0) * 60)
        : 0,
    };

    const qualityPayload = {
      quality_level: Number(formState.qualityBias || 0),
    };

    const configPayload = {
      search_terms: parseList(formState.keywords || ""),
      exclude_terms: parseList(formState.exclusions || ""),
      country: expandCountrySelection(formState.countries || []),
      client_regions: formState.countries || [],
      whatsapp_enabled: Boolean(formState.whatsappEnabled),
      whatsapp_waha_session: (formState.whatsappSession || selectedSlot?.slot_id || "").trim(),
      whatsapp_template: formState.whatsappTemplate || "",
      whatsapp_max_per_hour: Number(formState.whatsappMaxPerHour || 0),
      whatsapp_min_delay_s: Number(formState.whatsappMinDelay || 0),
      whatsapp_stop_on_reply: Boolean(formState.whatsappStopOnReply),
      indiamart_message_enabled: Boolean(formState.indiamartMessageEnabled),
      indiamart_message_template: formState.indiamartMessageTemplate || "",
      indiamart_message_max_per_day: Number(formState.indiamartMessageMaxPerDay || 0),
      indiamart_message_min_delay_s: Number(formState.indiamartMessageMinDelay || 0),
      client_schedule: {
        enabled: formState.windowEnabled,
        window_start: formState.windowEnabled ? formState.windowStart : "",
        window_end: formState.windowEnabled ? formState.windowEnd : "",
        days: formState.days,
        timezone: formState.timezone,
      },
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
                  : "Choose a slot to view controls."}
              </div>
            </div>
            <button
              className="engyne-btn engyne-btn--ghost engyne-btn--small"
              onClick={handleRemoteLogin}
              disabled={!selectedSlot}
            >
              <Monitor size={14} />
              Remote login
            </button>
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
                  {Number(selectedSlot.metrics?.leads_parsed || 0)}
                </div>
              </div>
              <div className="engyne-detail-card">
                <div className="engyne-detail-label">Heartbeat</div>
                <div className="engyne-detail-value">
                  {selectedSlot.last_heartbeat ? "Live" : "None"}
                </div>
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
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("maxRuntimeEnabled")}
                  disabled={fieldsDisabled}
                >
                  <span>Max runtime cap</span>
                  <span
                    className={
                      formState.maxRuntimeEnabled ? "engyne-toggle-pill is-on" : "engyne-toggle-pill"
                    }
                  >
                    {formState.maxRuntimeEnabled ? "On" : "Off"}
                  </span>
                </button>
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("windowEnabled")}
                  disabled={fieldsDisabled}
                >
                  <span>Run window schedule</span>
                  <span
                    className={
                      formState.windowEnabled ? "engyne-toggle-pill is-on" : "engyne-toggle-pill"
                    }
                  >
                    {formState.windowEnabled ? "On" : "Off"}
                  </span>
                </button>
              </div>
              <label className="engyne-field">
                <span>Lead target</span>
                <input
                  className="engyne-input"
                  type="number"
                  min="0"
                  value={formState.leadTarget}
                  onChange={(event) => updatePref("leadTarget", Number(event.target.value))}
                  disabled={fieldsDisabled || !formState.leadTargetEnabled}
                />
              </label>
              <label className="engyne-field">
                <span>Max runtime (hrs)</span>
                <input
                  className="engyne-input"
                  type="number"
                  min="0"
                  step="0.5"
                  value={formState.maxRuntime}
                  onChange={(event) => updatePref("maxRuntime", Number(event.target.value))}
                  disabled={fieldsDisabled || !formState.maxRuntimeEnabled}
                />
              </label>
              <label className="engyne-field">
                <span>Run window start</span>
                <input
                  className="engyne-input"
                  type="time"
                  value={formState.windowStart}
                  onChange={(event) => updatePref("windowStart", event.target.value)}
                  disabled={fieldsDisabled || !formState.windowEnabled}
                />
              </label>
              <label className="engyne-field">
                <span>Run window end</span>
                <input
                  className="engyne-input"
                  type="time"
                  value={formState.windowEnd}
                  onChange={(event) => updatePref("windowEnd", event.target.value)}
                  disabled={fieldsDisabled || !formState.windowEnabled}
                />
              </label>
              <div className="engyne-field">
                <span>Active days</span>
                <div className="engyne-inline-actions">
                  <button
                    className="engyne-btn engyne-btn--ghost engyne-btn--small"
                    type="button"
                    disabled={fieldsDisabled || !formState.windowEnabled}
                    onClick={() =>
                      updatePref(
                        "days",
                        DAY_OPTIONS.filter((day) => ["mon", "tue", "wed", "thu", "fri"].includes(day.key)).map((day) => day.key)
                      )
                    }
                  >
                    Weekdays
                  </button>
                  <button
                    className="engyne-btn engyne-btn--ghost engyne-btn--small"
                    type="button"
                    disabled={fieldsDisabled || !formState.windowEnabled}
                    onClick={() => updatePref("days", DAY_OPTIONS.map((day) => day.key))}
                  >
                    All days
                  </button>
                  <button
                    className="engyne-btn engyne-btn--ghost engyne-btn--small"
                    type="button"
                    disabled={fieldsDisabled || !formState.windowEnabled}
                    onClick={() => updatePref("days", [])}
                  >
                    Clear
                  </button>
                </div>
                <div className="engyne-checklist">
                  {DAY_OPTIONS.map((day) => (
                    <label key={day.key} className="engyne-check">
                      <input
                        type="checkbox"
                        disabled={fieldsDisabled || !formState.windowEnabled}
                        checked={formState.days.includes(day.key)}
                        onChange={() =>
                          updatePref("days", toggleListItem(formState.days, day.key))
                        }
                      />
                      <span>{day.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <label className="engyne-field">
                <span>Timezone</span>
                <select
                  className="engyne-input"
                  value={formState.timezone}
                  onChange={(event) => updatePref("timezone", event.target.value)}
                  disabled={fieldsDisabled || !formState.windowEnabled}
                >
                  {TIMEZONES.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz}
                    </option>
                  ))}
                </select>
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

          <div className="engyne-form-grid">
            <div>
              <div className="engyne-kicker">Messaging & automation</div>
              <div className="engyne-muted">
                Connect WhatsApp and configure IndiaMart first-message delivery.
              </div>
            </div>
            <div className="engyne-form-fields">
              <div className="engyne-toggle-list">
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("whatsappEnabled")}
                  disabled={fieldsDisabled}
                >
                  <span>WhatsApp messaging</span>
                  <span
                    className={
                      formState.whatsappEnabled ? "engyne-toggle-pill is-on" : "engyne-toggle-pill"
                    }
                  >
                    {formState.whatsappEnabled ? "On" : "Off"}
                  </span>
                </button>
                <button
                  className="engyne-toggle"
                  type="button"
                  onClick={() => togglePref("indiamartMessageEnabled")}
                  disabled={fieldsDisabled}
                >
                  <span>IndiaMart first message</span>
                  <span
                    className={
                      formState.indiamartMessageEnabled
                        ? "engyne-toggle-pill is-on"
                        : "engyne-toggle-pill"
                    }
                  >
                    {formState.indiamartMessageEnabled ? "On" : "Off"}
                  </span>
                </button>
              </div>

              <label className="engyne-field">
                <span>WhatsApp session name</span>
                <input
                  className="engyne-input"
                  value={formState.whatsappSession}
                  onChange={(event) => updatePref("whatsappSession", event.target.value)}
                  placeholder={selectedSlot?.slot_id || "slot_001"}
                  disabled={fieldsDisabled}
                />
              </label>

              <div className="engyne-inline-actions">
                <button
                  className="engyne-btn engyne-btn--primary engyne-btn--small"
                  type="button"
                  onClick={handleWhatsAppConnect}
                  disabled={fieldsDisabled || whatsappLoading}
                >
                  Connect WhatsApp
                </button>
                <button
                  className="engyne-btn engyne-btn--ghost engyne-btn--small"
                  type="button"
                  onClick={handleWhatsAppQr}
                  disabled={fieldsDisabled || whatsappLoading}
                >
                  Refresh QR
                </button>
                <button
                  className="engyne-btn engyne-btn--ghost engyne-btn--small"
                  type="button"
                  onClick={handleWhatsAppDisconnect}
                  disabled={fieldsDisabled || whatsappLoading}
                >
                  Disconnect
                </button>
              </div>

              {whatsappError && <div className="engyne-alert engyne-alert--danger">{whatsappError}</div>}

              {whatsappQr && (
                <div className="engyne-qr-card">
                  <img src={whatsappQr} alt="WhatsApp QR" />
                </div>
              )}

              <label className="engyne-field">
                <span>WhatsApp message template</span>
                <textarea
                  className="engyne-input engyne-textarea"
                  rows="3"
                  value={formState.whatsappTemplate}
                  onChange={(event) => updatePref("whatsappTemplate", event.target.value)}
                  disabled={fieldsDisabled || !formState.whatsappEnabled}
                />
              </label>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="engyne-field">
                  <span>WhatsApp max per hour</span>
                  <input
                    className="engyne-input"
                    type="number"
                    min="0"
                    value={formState.whatsappMaxPerHour}
                    onChange={(event) => updatePref("whatsappMaxPerHour", Number(event.target.value))}
                    disabled={fieldsDisabled || !formState.whatsappEnabled}
                  />
                </label>
                <label className="engyne-field">
                  <span>WhatsApp min delay (sec)</span>
                  <input
                    className="engyne-input"
                    type="number"
                    min="0"
                    value={formState.whatsappMinDelay}
                    onChange={(event) => updatePref("whatsappMinDelay", Number(event.target.value))}
                    disabled={fieldsDisabled || !formState.whatsappEnabled}
                  />
                </label>
              </div>

              <label className="engyne-check">
                <input
                  type="checkbox"
                  checked={formState.whatsappStopOnReply}
                  onChange={() => togglePref("whatsappStopOnReply")}
                  disabled={fieldsDisabled || !formState.whatsappEnabled}
                />
                <span>Stop messaging on reply</span>
              </label>

              <label className="engyne-field">
                <span>IndiaMart first message template</span>
                <textarea
                  className="engyne-input engyne-textarea"
                  rows="3"
                  value={formState.indiamartMessageTemplate}
                  onChange={(event) => updatePref("indiamartMessageTemplate", event.target.value)}
                  disabled={fieldsDisabled || !formState.indiamartMessageEnabled}
                />
              </label>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="engyne-field">
                  <span>IndiaMart max per day</span>
                  <input
                    className="engyne-input"
                    type="number"
                    min="0"
                    value={formState.indiamartMessageMaxPerDay}
                    onChange={(event) =>
                      updatePref("indiamartMessageMaxPerDay", Number(event.target.value))
                    }
                    disabled={fieldsDisabled || !formState.indiamartMessageEnabled}
                  />
                </label>
                <label className="engyne-field">
                  <span>IndiaMart min delay (sec)</span>
                  <input
                    className="engyne-input"
                    type="number"
                    min="0"
                    value={formState.indiamartMessageMinDelay}
                    onChange={(event) =>
                      updatePref("indiamartMessageMinDelay", Number(event.target.value))
                    }
                    disabled={fieldsDisabled || !formState.indiamartMessageEnabled}
                  />
                </label>
              </div>
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
