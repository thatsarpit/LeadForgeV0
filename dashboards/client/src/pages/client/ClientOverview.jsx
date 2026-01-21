import { useEffect, useMemo, useState } from "react";
import { CalendarClock, Monitor, Pause, Play, Sparkles, Target } from "lucide-react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { updateOnboardingComplete } from "../../services/auth";
import { fetchSlotClientLimits, fetchSlotConfig } from "../../services/api";
import StatCard from "../../components/StatCard";

const LOCAL_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAY_ALIASES = {
  mon: 1,
  monday: 1,
  tue: 2,
  tues: 2,
  tuesday: 2,
  wed: 3,
  weds: 3,
  wednesday: 3,
  thu: 4,
  thur: 4,
  thurs: 4,
  thursday: 4,
  fri: 5,
  friday: 5,
  sat: 6,
  saturday: 6,
  sun: 0,
  sunday: 0,
};

const parseDays = (value) => {
  if (!value) return null;
  const raw = Array.isArray(value) ? value : String(value).split(/,|\s/);
  const days = new Set();
  raw.forEach((token) => {
    const key = String(token).trim().toLowerCase();
    if (!key) return;
    const idx = DAY_ALIASES[key];
    if (typeof idx === "number") days.add(idx);
  });
  return days.size ? days : null;
};

const parseTime = (value) => {
  if (!value) return null;
  const [h, m] = String(value).split(":");
  const hour = Number(h);
  const minute = Number(m);
  if (Number.isNaN(hour) || Number.isNaN(minute)) return null;
  return hour * 60 + minute;
};

const formatTime = (minutes) => {
  if (minutes == null) return "--:--";
  const hour = Math.floor(minutes / 60)
    .toString()
    .padStart(2, "0");
  const minute = Math.floor(minutes % 60)
    .toString()
    .padStart(2, "0");
  return `${hour}:${minute}`;
};

const getZonedParts = (timeZone) => {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = formatter.formatToParts(new Date());
  const map = {};
  parts.forEach((part) => {
    map[part.type] = part.value;
  });
  const weekdayIndex = DAY_NAMES.findIndex((day) => day === map.weekday);
  return {
    weekdayIndex,
    hour: Number(map.hour),
    minute: Number(map.minute),
  };
};

const buildSchedulePreview = (schedule) => {
  if (!schedule || typeof schedule !== "object") {
    return {
      summary: "Set a schedule to control run windows.",
      status: "No schedule configured",
      window: "",
      timezone: LOCAL_TZ,
    };
  }
  if (schedule.enabled === false) {
    return {
      summary: "Run window scheduling is currently disabled.",
      status: "Scheduling off",
      window: "Anytime",
      timezone: schedule.timezone || LOCAL_TZ,
    };
  }

  const timezone = schedule.timezone || LOCAL_TZ;
  const start = parseTime(schedule.window_start);
  const end = parseTime(schedule.window_end);
  const days = parseDays(schedule.days);
  const now = getZonedParts(timezone);
  const currentMinutes = now.hour * 60 + now.minute;
  const windowLabel =
    start != null && end != null ? `${formatTime(start)} - ${formatTime(end)}` : "Anytime";
  const daysLabel = Array.isArray(schedule.days)
    ? schedule.days.map((day) => String(day).slice(0, 3)).join(", ")
    : schedule.days || "Every day";

  let status = "Next run scheduled";
  let nextLabel = "Upcoming";
  if (start != null && end != null) {
    if (!days || days.has(now.weekdayIndex)) {
      if (currentMinutes >= start && currentMinutes < end) {
        status = "Active now";
        nextLabel = "Today";
      } else if (currentMinutes < start) {
        nextLabel = "Today";
      } else {
        nextLabel = "Tomorrow";
      }
    } else {
      nextLabel = "Next run";
    }
  }

  return {
    summary: `${daysLabel} - ${windowLabel}`,
    status,
    window: `${nextLabel} - ${windowLabel}`,
    timezone,
  };
};

export default function ClientOverview() {
  const { slots, loading, error, actions } = useOutletContext();
  const { user, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingStatus, setOnboardingStatus] = useState("");
  const [schedulePreview, setSchedulePreview] = useState({
    summary: "Loading schedule...",
    status: "Loading...",
    window: "",
    timezone: LOCAL_TZ,
  });
  const [leadTarget, setLeadTarget] = useState(120);

  useEffect(() => {
    setShowOnboarding(Boolean(user) && !user.onboarding_complete);
  }, [user]);

  const summary = useMemo(() => {
    const total = slots.length;
    const running = slots.filter((s) => s.status === "RUNNING").length;
    const stopped = slots.filter((s) => s.status === "STOPPED").length;
    const totalLeads = slots.reduce(
      (acc, slot) => acc + Number(slot.metrics?.leads_parsed || 0),
      0
    );
    return { total, running, stopped, totalLeads };
  }, [slots]);

  const dailyGoal = leadTarget || 120;
  const goalProgress = Math.min(100, Math.round((summary.totalLeads / dailyGoal) * 100));

  const liveSlot = useMemo(
    () => slots.find((slot) => slot.status === "RUNNING") || slots[0],
    [slots]
  );

  useEffect(() => {
    if (!liveSlot) return;
    let alive = true;

    const loadSchedule = async () => {
      try {
        const nodeId = liveSlot.node_id;
        const [limitsRes, configRes] = await Promise.allSettled([
          fetchSlotClientLimits(liveSlot.slot_id, nodeId),
          fetchSlotConfig(liveSlot.slot_id, nodeId),
        ]);

        if (!alive) return;

        const limits = limitsRes.status === "fulfilled" ? limitsRes.value : {};
        const config = configRes.status === "fulfilled" ? configRes.value?.config || {} : {};
        const schedule = config.client_schedule || {};
        setLeadTarget(Number(limits.max_clicks_per_run || 120));
        setSchedulePreview(buildSchedulePreview(schedule));
      } catch (err) {
        if (!alive) return;
        setSchedulePreview(buildSchedulePreview({}));
      }
    };

    loadSchedule();

    return () => {
      alive = false;
    };
  }, [liveSlot?.slot_id, liveSlot?.node_id]);

  const alerts = useMemo(() => {
    const items = [];
    slots.forEach((slot) => {
      if (slot.status === "ERROR") {
        items.push({
          id: `${slot.slot_id}-error`,
          tone: "danger",
          title: "Slot error detected",
          detail: `${slot.slot_id} - ${slot.node_id || "local"}`,
        });
      }
      const phase = String(slot.metrics?.phase || "").toUpperCase();
      if (phase === "LOGIN_REQUIRED") {
        items.push({
          id: `${slot.slot_id}-login`,
          tone: "warn",
          title: "Login required",
          detail: `${slot.slot_id} - ${slot.node_id || "local"}`,
        });
      }
      if (slot.metrics?.last_error) {
        items.push({
          id: `${slot.slot_id}-last-error`,
          tone: "danger",
          title: "Recent slot error",
          detail: `${slot.slot_id} - ${slot.metrics.last_error}`,
        });
      }
    });
    return items.slice(0, 3);
  }, [slots]);

  const markOnboardingComplete = async () => {
    try {
      setOnboardingStatus("");
      await updateOnboardingComplete(true);
      setShowOnboarding(false);
      await refreshUser();
    } catch (err) {
      setOnboardingStatus("Unable to update onboarding status.");
    }
  };

  const handleRemoteLogin = () => {
    if (!liveSlot) return;
    const params = new URLSearchParams({
      slot: liveSlot.slot_id,
      node: liveSlot.node_id || "local",
    });
    window.open(`/remote-login?${params.toString()}`, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="engyne-page">
      {showOnboarding && (
        <section className="engyne-panel engyne-panel--highlight engyne-onboarding">
          <div className="engyne-card-header">
            <div>
              <div className="engyne-kicker">First-time setup</div>
              <div className="engyne-card-title">Let's get your workspace ready.</div>
              <div className="engyne-card-helper">
                Complete these steps to unlock scheduling, lead targets, and automated runs.
              </div>
            </div>
            <button
              className="engyne-btn engyne-btn--ghost engyne-btn--small"
              onClick={markOnboardingComplete}
            >
              Dismiss
            </button>
          </div>
          {onboardingStatus && (
            <div className="engyne-alert engyne-alert--danger">{onboardingStatus}</div>
          )}
          <div className="engyne-onboarding-grid">
            <div className="engyne-onboarding-step">
              <Sparkles size={18} />
              <div>
                <div className="engyne-onboarding-title">Confirm slots</div>
                <div className="engyne-onboarding-text">
                  Verify each slot is assigned and reachable before starting runs.
                </div>
              </div>
            </div>
            <div className="engyne-onboarding-step">
              <Target size={18} />
              <div>
                <div className="engyne-onboarding-title">Set lead targets</div>
                <div className="engyne-onboarding-text">
                  Choose daily lead goals and stop conditions per slot.
                </div>
              </div>
            </div>
            <div className="engyne-onboarding-step">
              <CalendarClock size={18} />
              <div>
                <div className="engyne-onboarding-title">Schedule runs</div>
                <div className="engyne-onboarding-text">
                  Pick operating windows and safe quiet hours for your team.
                </div>
              </div>
            </div>
          </div>
          <div className="engyne-onboarding-actions">
            <button
              className="engyne-btn engyne-btn--primary"
              onClick={() => navigate("/app/slots")}
            >
              Continue setup
            </button>
            <button
              className="engyne-btn engyne-btn--ghost"
              onClick={markOnboardingComplete}
            >
              Mark complete
            </button>
          </div>
        </section>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <StatCard label="Total slots" value={summary.total} tone="muted" helper="Assigned" />
        <StatCard label="Running" value={summary.running} tone="good" helper="Active now" />
        <StatCard label="Stopped" value={summary.stopped} tone="muted" helper="Awaiting run" />
        <StatCard label="Leads captured" value={summary.totalLeads} tone="default" helper="This session" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.15fr_0.85fr] gap-4">
        <div className="space-y-4">
          <section className="engyne-panel-soft engyne-card">
            <div className="engyne-card-header">
              <div>
                <div className="engyne-kicker">Live slot</div>
                <div className="engyne-card-title">
                  {liveSlot ? liveSlot.slot_id : "No slots assigned"}
                </div>
                <div className="engyne-card-helper">
                  {liveSlot
                    ? `${liveSlot.node_id || "local"} - ${liveSlot.status}`
                    : "Assign slots to begin running leads."}
                </div>
              </div>
              {liveSlot && (
                <span
                  className={`engyne-pill ${
                    liveSlot.status === "RUNNING" ? "engyne-pill--good" : ""
                  }`}
                >
                  {liveSlot.status}
                </span>
              )}
            </div>

            {loading && <div className="engyne-muted">Loading slots...</div>}
            {error && <div className="engyne-alert engyne-alert--danger">{error}</div>}

            {liveSlot && (
              <div className="engyne-inline-actions">
                {liveSlot.status === "RUNNING" ? (
                  <button
                    className="engyne-btn engyne-btn--ghost"
                    onClick={() => actions.stop(liveSlot)}
                  >
                    <Pause size={14} />
                    Pause slot
                  </button>
                ) : (
                  <button
                    className="engyne-btn engyne-btn--primary"
                    onClick={() => actions.start(liveSlot)}
                  >
                    <Play size={14} />
                    Start slot
                  </button>
                )}
                <button
                  className="engyne-btn engyne-btn--ghost"
                  onClick={handleRemoteLogin}
                >
                  <Monitor size={14} />
                  Remote login
                </button>
              </div>
            )}
          </section>

          <section className="engyne-panel-soft engyne-card">
            <div className="engyne-card-header">
              <div>
                <div className="engyne-kicker">Scheduler preview</div>
                <div className="engyne-card-title">Next run window</div>
                <div className="engyne-card-helper">{schedulePreview.summary}</div>
              </div>
              <button
                className="engyne-btn engyne-btn--ghost engyne-btn--small"
                onClick={() => navigate("/app/slots")}
              >
                Edit schedule
              </button>
            </div>
            <div className="engyne-progress">
              <span style={{ width: `${goalProgress}%` }} />
            </div>
            <div className="engyne-muted">
              {schedulePreview.status} - {schedulePreview.window} - {schedulePreview.timezone}
            </div>
            <div className="engyne-muted">
              {summary.totalLeads} leads captured toward today's target of {dailyGoal}.
            </div>
          </section>
        </div>

        <div className="space-y-4">
          <section className="engyne-panel engyne-card">
            <div className="engyne-card-header">
              <div>
                <div className="engyne-kicker">Health signals</div>
                <div className="engyne-card-title">Operational attention</div>
                <div className="engyne-card-helper">
                  Recent items that may need your review.
                </div>
              </div>
              <button className="engyne-btn engyne-btn--ghost engyne-btn--small" onClick={() => navigate("/app/alerts")}>
                View alerts
              </button>
            </div>
            {alerts.length === 0 ? (
              <div className="engyne-muted">All systems stable.</div>
            ) : (
              <div className="engyne-alert-stack">
                {alerts.map((alert) => (
                  <div key={alert.id} className={`engyne-alert engyne-alert--${alert.tone}`}>
                    <div className="engyne-alert-title">{alert.title}</div>
                    <div className="engyne-alert-text">{alert.detail}</div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="engyne-panel engyne-card">
            <div className="engyne-card-header">
              <div>
                <div className="engyne-kicker">Trends</div>
                <div className="engyne-card-title">Analytics in progress</div>
                <div className="engyne-card-helper">
                  We'll surface lead velocity and quality once analytics are enabled.
                </div>
              </div>
            </div>
            <div className="engyne-muted">Connect analytics to unlock trend reports.</div>
          </section>
        </div>
      </div>
    </div>
  );
}
