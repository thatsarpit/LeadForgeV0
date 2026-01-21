import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink } from "react-router-dom";

export default function Sidebar({
  brand = "Engyne",
  collapsed = false,
  onToggle,
  items = [],
  activeId,
}) {
  return (
    <aside className={`engyne-sidebar ${collapsed ? "is-collapsed" : ""}`}>
      <div className="engyne-sidebar-brand">
        <div className="engyne-brand-mark">{brand.slice(0, 1)}</div>
        {!collapsed && (
          <div className="engyne-brand-text">
            <div className="engyne-brand-kicker">Engyne</div>
            <div className="engyne-brand-title">{brand}</div>
          </div>
        )}
        <button
          type="button"
          className="engyne-btn engyne-btn--ghost engyne-btn--small"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
        </button>
      </div>

      <nav className="engyne-sidebar-nav">
        {items.map((item) => {
          const content = (
            <>
              {item.icon && <item.icon size={16} />}
              {!collapsed && <span>{item.label}</span>}
              {!collapsed && item.badge && (
                <span className="engyne-sidebar-badge">{item.badge}</span>
              )}
            </>
          );

          if (item.to) {
            return (
              <NavLink
                key={item.id}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `engyne-sidebar-item ${isActive ? "is-active" : ""}`
                }
                title={collapsed ? item.label : undefined}
              >
                {content}
              </NavLink>
            );
          }

          const isActive = activeId === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={`engyne-sidebar-item ${isActive ? "is-active" : ""}`}
              onClick={item.onClick}
              title={collapsed ? item.label : undefined}
            >
              {content}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
