export default function DashboardLayout({
  title,
  subtitle,
  sidebar = null,
  headerRight = null,
  children,
}) {
  return (
    <div className="engyne-shell">
      {sidebar}
      <div className="engyne-shell-main">
        <header className="engyne-topbar">
          <div>
            <div className="engyne-topbar-title">{title}</div>
            {subtitle && <div className="engyne-topbar-subtitle">{subtitle}</div>}
          </div>
          <div className="engyne-topbar-actions">{headerRight}</div>
        </header>
        <main className="engyne-content">{children}</main>
      </div>
    </div>
  );
}
