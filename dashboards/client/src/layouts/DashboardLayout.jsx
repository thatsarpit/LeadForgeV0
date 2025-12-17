import MetricsStrip from "../components/layout/MetricsStrip";

/**
 * DashboardLayout
 * ----------------
 * Global application shell ONLY.
 * - Owns header and global metrics
 * - Renders children as-is (no logic, no functions)
 * - No observer mode logic
 * - No slot-specific logic
 */

export default function DashboardLayout({ title = "LeadForge — Client Dashboard", children }) {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-200">
      {/* HEADER */}
      <header className="sticky top-0 z-20 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <h1 className="text-sm font-bold tracking-wide uppercase">
            {title}
          </h1>
        </div>
      </header>

      {/* GLOBAL METRICS */}
      <section className="max-w-7xl mx-auto px-6 pt-4">
        <MetricsStrip />
      </section>

      {/* PAGE CONTENT */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        {children}
      </main>
    </div>
  );
}