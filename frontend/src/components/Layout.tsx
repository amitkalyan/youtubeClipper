import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

const ITEMS: { to: string; label: string; phase?: string }[] = [
  { to: "/", label: "Dashboard" },
  { to: "/new", label: "New Project" },
  { to: "/analysis", label: "Video Analysis" },
  { to: "/history", label: "Processing History" },
  { to: "/highlights", label: "Highlight Detection" },
  { to: "/shorts", label: "Generated Shorts" },
  { to: "/preview", label: "Video Preview" },
  { to: "/thumbnails", label: "Thumbnail Studio" },
  { to: "/metadata", label: "Metadata Editor" },
  { to: "/settings", label: "Settings" },
];

function isActive(pathname: string, to: string): boolean {
  if (to === "/") return pathname === "/";
  if (to === "/analysis") return pathname === "/analysis" || pathname.startsWith("/projects/");
  return pathname === to;
}

export function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen bg-[#0c0d10] text-[#e7e9ee]">
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-white/10 bg-[#12141a] md:flex">
        <div className="px-5 py-6">
          <p className="text-lg font-semibold tracking-tight">Clipper</p>
          <p className="mt-1 text-xs text-zinc-500">Local Shorts studio</p>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3" aria-label="Primary">
          {ITEMS.map((item) => (
            <NavItem key={item.to} item={item} active={isActive(pathname, item.to)} />
          ))}
        </nav>
        <p className="px-5 py-4 text-xs leading-5 text-zinc-500">CPU profile · one job at a time</p>
      </aside>
      <div className="md:pl-64">
        <header className="border-b border-white/10">
          <div className="flex items-center justify-between px-4 py-3 md:px-8">
            <p className="text-sm font-medium md:hidden">Clipper</p>
            <p className="hidden text-sm text-zinc-400 md:block">Personal workstation</p>
            <p className="text-xs text-amber-200/90 md:text-sm">CPU only · one job at a time</p>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:hidden" aria-label="Primary">
            {ITEMS.map((item) => (
              <NavItem key={item.to} item={item} active={isActive(pathname, item.to)} compact />
            ))}
          </nav>
        </header>
        <main className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}

function NavItem({
  item,
  active,
  compact = false,
}: {
  item: (typeof ITEMS)[number];
  active: boolean;
  compact?: boolean;
}) {
  return (
    <Link
      to={item.to}
      className={`flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm ${
        compact ? "shrink-0" : ""
      } ${active ? "bg-white/10 text-white" : "text-zinc-400 hover:bg-white/5 hover:text-zinc-100"}`}
      aria-current={active ? "page" : undefined}
    >
      <span>{item.label}</span>
      {item.phase ? (
        <span className="text-[10px] uppercase tracking-wide text-zinc-500">{item.phase}</span>
      ) : null}
    </Link>
  );
}
