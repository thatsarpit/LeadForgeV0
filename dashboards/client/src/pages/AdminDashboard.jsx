import { useMemo, useState } from "react";
import { RefreshCcw, LogOut, LayoutGrid, Layers, Users, SlidersHorizontal, Server } from "lucide-react";
import { Outlet, useLocation } from "react-router-dom";
import DashboardLayout from "../layouts/DashboardLayout";
import Sidebar from "../components/layout/Sidebar";
import useSlots from "../hooks/useSlots";
import { useAuth } from "../context/AuthContext";

const PAGE_META = [
  {
    id: "overview",
    path: "/admin",
    title: "Admin Command",
    subtitle: "Control slots, monitor performance, and keep the system healthy.",
  },
  {
    id: "slots",
    path: "/admin/slots",
    title: "Slot Operations",
    subtitle: "Monitor slot health across nodes and action issues fast.",
  },
  {
    id: "clients",
    path: "/admin/clients",
    title: "Client Control",
    subtitle: "Manage client access, assignments, and onboarding.",
  },
  {
    id: "policies",
    path: "/admin/policies",
    title: "Policies & Guardrails",
    subtitle: "Set global limits, fallbacks, and automation rules.",
  },
  {
    id: "integrations",
    path: "/admin/integrations",
    title: "Integrations",
    subtitle: "Manage messaging, status pages, and delivery providers.",
  },
];

export default function AdminDashboard() {
  const { user, logout } = useAuth();
  const { slots, loading, error, refresh, actions } = useSlots({ pollInterval: 4000 });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const location = useLocation();

  const pageMeta = useMemo(() => {
    const sorted = [...PAGE_META].sort((a, b) => b.path.length - a.path.length);
    return sorted.find((entry) => location.pathname.startsWith(entry.path)) || PAGE_META[0];
  }, [location.pathname]);

  const errorCount = useMemo(() => {
    return slots.filter((slot) => slot.status === "ERROR" || slot.metrics?.last_error).length;
  }, [slots]);

  const navItems = [
    { id: "overview", label: "Overview", icon: LayoutGrid, to: "/admin", end: true },
    {
      id: "slots",
      label: "Slots",
      icon: Layers,
      to: "/admin/slots",
      badge: errorCount > 0 ? errorCount : null,
    },
    { id: "clients", label: "Clients", icon: Users, to: "/admin/clients" },
    { id: "policies", label: "Policies", icon: SlidersHorizontal, to: "/admin/policies" },
    { id: "integrations", label: "Integrations", icon: Server, to: "/admin/integrations" },
  ];

  return (
    <DashboardLayout
      title={pageMeta.title}
      subtitle={pageMeta.subtitle}
      sidebar={
        <Sidebar
          brand="Admin Command"
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
