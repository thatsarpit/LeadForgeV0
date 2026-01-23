import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import { finishRemoteLogin, startRemoteLogin } from "../services/api";
import { getToken } from "../services/auth";

export default function RemoteLogin() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const slotId = searchParams.get("slot");
  const nodeId = searchParams.get("node");
  const [session, setSession] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [status, setStatus] = useState("starting");

  const containerRef = useRef(null);
  const imgRef = useRef(null);
  const wsRef = useRef(null);
  const lastFrameRef = useRef(0);
  const pollRef = useRef(null);

  const viewport = useMemo(() => {
    return session?.viewport || { width: 1280, height: 800 };
  }, [session]);

  useEffect(() => {
    if (!slotId) {
      setError("Missing slot reference.");
      return;
    }

    let cancelled = false;

    const begin = async () => {
      try {
        const data = await startRemoteLogin(slotId, nodeId);
        if (cancelled) return;
        setSession(data);
        setStatus(data.status || "starting");
      } catch (err) {
        if (!cancelled) {
          setError(err?.message || "Failed to start remote login");
        }
      }
    };

    begin();
    return () => {
      cancelled = true;
    };
  }, [slotId, nodeId]);

  useEffect(() => {
    if (!session?.ws_url) return;

    const token = getToken();
    const wsUrl = new URL(session.ws_url);
    if (token) {
      wsUrl.searchParams.set("token", token);
    }

    const ws = new WebSocket(wsUrl.toString());
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "frame" && imgRef.current) {
          imgRef.current.src = `data:image/jpeg;base64,${payload.data}`;
          const prev = imgRef.current.dataset.frameUrl;
          if (prev) {
            URL.revokeObjectURL(prev);
            delete imgRef.current.dataset.frameUrl;
          }
          lastFrameRef.current = Date.now();
        }
        if (payload.type === "status") {
          setStatus(payload.status || "active");
          if (payload.error) {
            setError(payload.error);
          }
        }
      } catch (err) {
        return;
      }
    };

    return () => {
      ws.close();
    };
  }, [session]);

  useEffect(() => {
    if (!session?.session_id) return;
    let stopped = false;

    const tick = async () => {
      if (stopped) return;
      const idleFor = Date.now() - lastFrameRef.current;
      if (idleFor < 1500) {
        pollRef.current = window.setTimeout(tick, 1000);
        return;
      }
      try {
        const base = session.api_base || window.location.origin;
        const url = new URL(`/remote-login/sessions/${session.session_id}/frame`, base);
        url.searchParams.set("_", Date.now().toString());
        const token = getToken();
        const res = await fetch(url.toString(), {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (res.ok) {
          const blob = await res.blob();
          if (imgRef.current) {
            const objUrl = URL.createObjectURL(blob);
            const prev = imgRef.current.dataset.frameUrl;
            imgRef.current.src = objUrl;
            imgRef.current.dataset.frameUrl = objUrl;
            lastFrameRef.current = Date.now();
            if (prev) {
              URL.revokeObjectURL(prev);
            }
          }
        }
      } catch (err) {
        // Ignore polling errors; WS frames will take precedence when available.
      } finally {
        pollRef.current = window.setTimeout(tick, 1000);
      }
    };

    tick();
    return () => {
      stopped = true;
      if (pollRef.current) {
        window.clearTimeout(pollRef.current);
      }
      if (imgRef.current?.dataset?.frameUrl) {
        URL.revokeObjectURL(imgRef.current.dataset.frameUrl);
      }
    };
  }, [session]);

  const sendMessage = (payload) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify(payload));
  };

  const mapPointer = (event) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    const x = ((event.clientX - rect.left) / rect.width) * viewport.width;
    const y = ((event.clientY - rect.top) / rect.height) * viewport.height;
    return { x, y };
  };

  const handleMouse = (event, type) => {
    if (!containerRef.current) return;
    const { x, y } = mapPointer(event);
    const button =
      event.button === 2 ? "right" : event.button === 1 ? "middle" : "left";
    sendMessage({ type: "mouse", event: type, x, y, button });
  };

  const handleWheel = (event) => {
    sendMessage({
      type: "mouse",
      event: "wheel",
      dx: event.deltaX,
      dy: event.deltaY,
    });
  };

  const handleKeyDown = (event) => {
    if (event.metaKey || event.ctrlKey) return;
    const key = event.key === " " ? "Space" : event.key;
    if (event.key.length === 1) {
      sendMessage({ type: "key", action: "type", text: event.key });
      event.preventDefault();
      return;
    }
    sendMessage({ type: "key", action: "press", key });
    event.preventDefault();
  };

  const handleFinish = async () => {
    if (!session?.session_id) return;
    setFinishing(true);
    try {
      await finishRemoteLogin(session.session_id, session.api_base, nodeId);
      setStatus("finished");
      window.setTimeout(() => {
        if (window.opener) {
          window.close();
          return;
        }
        navigate(-1);
      }, 400);
    } catch (err) {
      setError(err?.message || "Failed to finish login");
    } finally {
      setFinishing(false);
    }
  };

  return (
    <div className="engyne-remote-shell">
      <header className="engyne-remote-header">
        <button className="engyne-btn engyne-btn--ghost engyne-btn--small" onClick={() => navigate(-1)}>
          <ArrowLeft size={14} />
          Back
        </button>
        <div className="engyne-remote-title">
          <div className="engyne-kicker">Remote Login</div>
          <div className="engyne-remote-subtitle">
            Slot {slotId || "—"} · {nodeId || "local"}
          </div>
        </div>
        <div className="engyne-remote-actions">
          <div className={`engyne-pill ${connected ? "engyne-pill--good" : ""}`}>
            {connected ? "connected" : "offline"}
          </div>
          <button className="engyne-btn engyne-btn--primary engyne-btn--small" onClick={handleFinish} disabled={finishing}>
            {finishing ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
            Finish & save
          </button>
        </div>
      </header>

      {error && <div className="engyne-remote-error">{error}</div>}

      <section className="engyne-remote-stage">
        <div className="engyne-remote-status">
          <CheckCircle2 size={14} />
          <span>{status}</span>
        </div>
        <div
          className="engyne-remote-viewer"
          ref={containerRef}
          onMouseMove={(event) => handleMouse(event, "move")}
          onMouseDown={(event) => handleMouse(event, "down")}
          onMouseUp={(event) => handleMouse(event, "up")}
          onClick={(event) => handleMouse(event, "click")}
          onWheel={handleWheel}
          onKeyDown={handleKeyDown}
          tabIndex={0}
        >
          {!connected && (
            <div className="engyne-remote-placeholder">
              <Loader2 size={18} className="animate-spin" />
              Connecting to secure browser…
            </div>
          )}
          <img ref={imgRef} alt="Remote login view" />
        </div>
      </section>
    </div>
  );
}
