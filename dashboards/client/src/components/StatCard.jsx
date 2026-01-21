import AnimatedNumber from "./AnimatedNumber";

const TONE_CLASS = {
  good: "engyne-pill engyne-pill--good",
  warn: "engyne-pill engyne-pill--warn",
  danger: "engyne-pill engyne-pill--danger",
  muted: "engyne-pill",
  default: "engyne-pill",
};

export default function StatCard({ label, value, tone = "default", helper, badge }) {
  const pillLabel = badge ?? (tone === "muted" || tone === "default" ? "ok" : tone);

  return (
    <div className="engyne-panel engyne-card">
      <div className="engyne-card-header">
        <div>
          <div className="engyne-kicker">{label}</div>
          {helper && <div className="engyne-card-helper">{helper}</div>}
        </div>
        <span className={TONE_CLASS[tone] || TONE_CLASS.default}>{pillLabel}</span>
      </div>
      <AnimatedNumber value={value} className="engyne-stat-value engyne-mono" />
    </div>
  );
}
