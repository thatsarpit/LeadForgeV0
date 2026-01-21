import { useEffect, useMemo, useState } from "react";
import { Building2, Chrome, KeyRound, Mail } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { getGoogleLoginUrl } from "../services/auth";

export default function Login() {
  const { error, demoLogin, user, token, loading, bootstrapped } = useAuth();
  const navigate = useNavigate();
  const googleLoginUrl = getGoogleLoginUrl(`${window.location.origin}/login`);
  const demoEnabled = import.meta.env.VITE_DEMO_LOGIN_ENABLED === "true";
  const [demoCode, setDemoCode] = useState("");
  const [demoError, setDemoError] = useState("");
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);

  useEffect(() => {
    if (!bootstrapped || loading) return;
    if (!token || !user) return;
    navigate(user.role === "admin" ? "/admin" : "/app", { replace: true });
  }, [bootstrapped, loading, token, user, navigate]);

  const providers = useMemo(
    () => [
      {
        id: "google",
        label: "Continue with Google",
        icon: Chrome,
        href: googleLoginUrl,
        primary: true,
        enabled: true,
      },
      {
        id: "email",
        label: "Email magic link",
        icon: Mail,
        enabled: false,
        note: "Coming soon",
      },
      {
        id: "sso",
        label: "Company SSO",
        icon: Building2,
        enabled: false,
        note: "Coming soon",
      },
      {
        id: "passkey",
        label: "Passkey",
        icon: KeyRound,
        enabled: false,
        note: "Coming soon",
      },
    ],
    [googleLoginUrl]
  );

  const onDemoSubmit = async (event) => {
    event.preventDefault();
    const code = demoCode.trim();
    if (!code) {
      setDemoError("Enter a demo code.");
      return;
    }
    setDemoLoading(true);
    setDemoError("");
    try {
      await demoLogin(code);
    } catch (err) {
      setDemoError("Invalid demo code.");
    } finally {
      setDemoLoading(false);
    }
  };

  return (
    <div className="engyne-login-shell">
      <section className="engyne-login-hero">
        <div className="engyne-login-badge">Secure Access</div>
        <h1 className="engyne-login-title">Engyne Control</h1>
        <p className="engyne-login-subtitle">
          A focused workspace for lead operations, slot health, and live control.
        </p>
        <div className="engyne-login-feature-grid">
          <div className="engyne-login-feature">
            <div className="engyne-login-feature-title">Real-time command</div>
            <div className="engyne-login-feature-text">
              Start, pause, and monitor slots with precise operational context.
            </div>
          </div>
          <div className="engyne-login-feature">
            <div className="engyne-login-feature-title">Guided onboarding</div>
            <div className="engyne-login-feature-text">
              First-time setup walks clients through slots, limits, and scheduling.
            </div>
          </div>
          <div className="engyne-login-feature">
            <div className="engyne-login-feature-title">Client-first security</div>
            <div className="engyne-login-feature-text">
              Google-only access with per-client slot permissions and audit history.
            </div>
          </div>
        </div>
        <div className="engyne-login-meta">
          Built for secure operations on the Engyne network.
        </div>
      </section>

      <section className="engyne-login-card engyne-panel">
        <div className="engyne-login-card-header">
          <div>
            <div className="engyne-kicker">Sign in</div>
            <h2 className="engyne-login-card-title">Welcome back</h2>
          </div>
          <div className="engyne-login-card-chip">Invited access only</div>
        </div>

        {error && <div className="engyne-login-error">{error}</div>}

        <div className="engyne-login-providers">
          {providers.map((provider) => {
            const Icon = provider.icon;
            const className = [
              "engyne-login-provider",
              provider.primary ? "is-primary" : "",
              !provider.enabled ? "is-disabled" : "",
            ]
              .filter(Boolean)
              .join(" ");

            if (provider.href) {
              return (
                <a key={provider.id} href={provider.href} className={className}>
                  <Icon size={18} />
                  <span className="engyne-login-provider-label">{provider.label}</span>
                </a>
              );
            }

            return (
              <button key={provider.id} className={className} disabled={!provider.enabled}>
                <Icon size={18} />
                <span className="engyne-login-provider-label">{provider.label}</span>
                {provider.note && (
                  <span className="engyne-login-provider-note">{provider.note}</span>
                )}
              </button>
            );
          })}
        </div>

        <div className="engyne-login-divider">
          <span>or</span>
        </div>

        <button
          className="engyne-login-demo-trigger"
          onClick={() => setDemoOpen((prev) => !prev)}
        >
          Demo login
          <span className="engyne-login-badge">{demoEnabled ? "Active" : "Off"}</span>
        </button>

        {demoOpen && (
          <form onSubmit={onDemoSubmit} className="engyne-login-demo">
            <input
              type="text"
              value={demoCode}
              onChange={(event) => setDemoCode(event.target.value)}
              placeholder="Enter demo code"
              className="engyne-input"
              autoComplete="off"
              disabled={!demoEnabled}
            />
            {demoError && <div className="engyne-login-error">{demoError}</div>}
            {!demoEnabled && (
              <div className="engyne-login-muted">
                Demo access is enabled only on the demo environment.
              </div>
            )}
            <button
              type="submit"
              className="w-full engyne-btn engyne-btn--block justify-center"
              disabled={!demoEnabled || demoLoading}
            >
              {demoLoading ? "Checking code..." : "Continue with demo code"}
            </button>
          </form>
        )}

        <div className="engyne-login-footnote">
          Access is granted to invited Google accounts only.
        </div>
      </section>
    </div>
  );
}
