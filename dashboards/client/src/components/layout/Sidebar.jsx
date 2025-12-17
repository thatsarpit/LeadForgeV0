export default function Sidebar() {
  return (
    <aside style={{
      width: 220,
      background: "#0f172a",
      color: "#e5e7eb",
      padding: 16
    }}>
      <h2 style={{ fontWeight: 600, marginBottom: 24 }}>
        LeadForge
      </h2>

      <nav style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <span>📊 Dashboard</span>
        <span>🤖 Slot Status</span>
        <span>🧠 Observer Mode</span>
        <span>⚙️ Settings</span>
      </nav>
    </aside>
  )
}
