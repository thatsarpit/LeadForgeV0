import { useMemo, useState } from "react";
import { LayoutGrid, Layers, List, Bell, Settings, RefreshCcw, LogOut } from "lucide-react";
import { Outlet, useLocation } from "react-router-dom";
import DashboardLayout from "../layouts/DashboardLayout";
import Sidebar from "../components/layout/Sidebar";
import useSlots from "../hooks/useSlots";
import { useAuth } from "../context/AuthContext";

const PAGE_META = [
  {
    id: "home",
    path: "/app",
    title: "Client Command",
    subtitle: "Monitor your slots and react quickly to new leads.",
  },
  {
    id: "leads",
    path: "/app/leads",
    title: "Lead Desk",
    subtitle: "Track incoming leads and export qualified data.",
  },
  {
    id: "slots",
    path: "/app/slots",
    title: "Slot Control",
    subtitle: "Tune schedules, keywords, and run modes per slot.",
  },
  {
    id: "alerts",
    path: "/app/alerts",
    title: "Operational Alerts",
    subtitle: "Stay ahead of login events, downtime, and errors.",
  },
  {
    id: "settings",
    path: "/app/settings",
    title: "Workspace Settings",
    subtitle: "Manage notifications, security, and workspace defaults.",
  },
];

export default function ClientDashboard() {
  const { user, logout } = useAuth();
  const { slots, loading, error, refresh, actions } = useSlots({ pollInterval: 5000 });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const location = useLocation();

  const pageMeta = useMemo(() => {
    const sorted = [...PAGE_META].sort((a, b) => b.path.length - a.path.length);
    return sorted.find((entry) => location.pathname.startsWith(entry.path)) || PAGE_META[0];
  }, [location.pathname]);

  const attentionCount = useMemo(() => {
    return slots.filter((slot) => {
      const phase = String(slot.metrics?.phase || "").toUpperCase();
      return slot.status === "ERROR" || phase === "LOGIN_REQUIRED";
    }).length;
  }, [slots]);

  const navItems = [
    { id: "home", label: "Home", icon: LayoutGrid, to: "/app", end: true },
    { id: "leads", label: "Leads", icon: List, to: "/app/leads" },
    { id: "slots", label: "Slots", icon: Layers, to: "/app/slots" },
    {
      id: "alerts",
      label: "Alerts",
      icon: Bell,
      to: "/app/alerts",
      badge: attentionCount > 0 ? attentionCount : null,
    },
    { id: "settings", label: "Settings", icon: Settings, to: "/app/settings" },
  ];

  return (
    <DashboardLayout
      title={pageMeta.title}
      subtitle={pageMeta.subtitle}
      sidebar={
        <Sidebar
          brand="Client Command"
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed((prev) => !prev)}
          items={navItems}
          activeId={pageMeta.id}
        />
      }
      headerRight={
        <>
          {user && (
            <div className="engyne-chip">
              <span className="text-[var(--engyne-text)]">{user.sub}</span> | {user.role}
            </div>
          )}
          <button className="engyne-btn engyne-btn--ghost engyne-btn--small" onClick={refresh}>
            <RefreshCcw size={14} />
            Refresh
          </button>
          <button className="engyne-btn engyne-btn--ghost engyne-btn--small" onClick={logout}>
            <LogOut size={14} />
            Logout
          </button>
        </>
      }
    >
      <Outlet
        context={{
          slots,
          loading,
          error,
          refresh,
          actions,
        }}
      />
    </DashboardLayout>
  );
}
