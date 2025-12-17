export default function Header() {
  return (
    <header style={{
      height: 56,
      borderBottom: "1px solid #1e293b",
      display: "flex",
      alignItems: "center",
      padding: "0 20px",
      justifyContent: "space-between"
    }}>
      <strong>Slot: slot_001</strong>
      <span style={{ color: "#22c55e" }}>● RUNNING</span>
    </header>
  )
}
