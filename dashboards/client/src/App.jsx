import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import useTheme from "./hooks/useTheme";
import AdminDashboard from "./pages/AdminDashboard";
import AdminClients from "./pages/admin/AdminClients";
import AdminIntegrations from "./pages/admin/AdminIntegrations";
import AdminOverview from "./pages/admin/AdminOverview";
import AdminPolicies from "./pages/admin/AdminPolicies";
import AdminSlots from "./pages/admin/AdminSlots";
import ClientDashboard from "./pages/ClientDashboard";
import ClientAlerts from "./pages/client/ClientAlerts";
import ClientLeads from "./pages/client/ClientLeads";
import ClientOverview from "./pages/client/ClientOverview";
import ClientSettings from "./pages/client/ClientSettings";
import ClientSlots from "./pages/client/ClientSlots";
import Login from "./pages/Login";
import RemoteLogin from "./pages/RemoteLogin";

function RequireAuth({ children, role }) {
  const { user, token, loading, bootstrapped } = useAuth();

  if (!bootstrapped || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-[var(--engyne-muted)]">
        Loading...
      </div>
    );
  }

  if (!token || !user) {
    return <Navigate to="/login" replace />;
  }

  if (role && user.role !== role) {
    return <Navigate to="/app" replace />;
  }

  if (!role && user.role === "admin") {
    return <Navigate to="/admin" replace />;
  }

  return children;
}

export default function App() {
  useTheme();
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/remote-login"
            element={
              <RequireAuth>
                <RemoteLogin />
              </RequireAuth>
            }
          />
          <Route
            path="/admin"
            element={
              <RequireAuth role="admin">
                <AdminDashboard />
              </RequireAuth>
            }
          >
            <Route index element={<AdminOverview />} />
            <Route path="slots" element={<AdminSlots />} />
            <Route path="clients" element={<AdminClients />} />
            <Route path="policies" element={<AdminPolicies />} />
            <Route path="integrations" element={<AdminIntegrations />} />
          </Route>
          <Route
            path="/app"
            element={
              <RequireAuth>
                <ClientDashboard />
              </RequireAuth>
            }
          >
            <Route index element={<ClientOverview />} />
            <Route path="leads" element={<ClientLeads />} />
            <Route path="slots" element={<ClientSlots />} />
            <Route path="alerts" element={<ClientAlerts />} />
            <Route path="settings" element={<ClientSettings />} />
          </Route>
          <Route path="*" element={<Navigate to="/app" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
