import { useQuery } from "@tanstack/react-query";
import {
  Activity, Building2, ChevronDown, ClipboardList, Factory, FlaskConical, Gauge, Globe2, LayoutDashboard, LogOut,
  Map, Menu, PlayCircle, ScrollText, ShieldCheck, Sparkles, UserCog, Users,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { ROLE_LABEL, timeAgo } from "../../lib/format";
import { useLogout, type Me } from "../../lib/session";

type OrgLite = { slug: string; name: string; city: string };

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 shadow-lg shadow-brand-900/40">
        <svg viewBox="0 0 32 32" className="h-5 w-5"><path d="M8 23V9l8 9 8-9v14" stroke="white" strokeWidth="3.2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </div>
      <div className="leading-tight">
        <div className="font-display text-[15px] font-extrabold tracking-tight text-white">NSQ Intelligence</div>
        <div className="text-[10.5px] font-medium text-slate-400">Quality · Capability · Export</div>
      </div>
    </div>
  );
}

function NavItem({ to, icon, children, end }: { to: string; icon: ReactNode; children: ReactNode; end?: boolean }) {
  return (
    <NavLink to={to} end={end} className="group relative block">
      {({ isActive }) => (
        <div className={cn("relative flex items-center gap-3 rounded-xl px-3 py-2 text-[13.5px] font-medium transition", isActive ? "text-white" : "text-slate-400 hover:bg-white/5 hover:text-slate-200")}>
          {isActive && <motion.div layoutId="nav-active" className="absolute inset-0 rounded-xl bg-white/10 ring-1 ring-inset ring-white/10" transition={{ type: "spring", damping: 30, stiffness: 380 }} />}
          {isActive && <motion.div layoutId="nav-bar" className="absolute -left-3 top-1.5 h-6 w-1 rounded-r-full bg-brand-400" />}
          <span className={cn("relative", isActive ? "text-brand-400" : "")}>{icon}</span>
          <span className="relative">{children}</span>
        </div>
      )}
    </NavLink>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-0.5">
      <div className="px-3 pb-1.5 pt-4 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-slate-500">{title}</div>
      {children}
    </div>
  );
}

function OrgSwitcher({ me, current }: { me: Me; current?: string }) {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const { data } = useQuery({ queryKey: ["my-orgs"], queryFn: () => api<{ orgs: OrgLite[] }>("/api/orgs") });
  const orgs = data?.orgs ?? [];
  const cur = orgs.find((o) => o.slug === current) ?? (me.org ? { slug: me.org.slug, name: me.org.name, city: me.org.city } : undefined);
  const filtered = orgs.filter((o) => o.name.toLowerCase().includes(q.toLowerCase()));
  if (!me.is_platform && me.org) {
    return (
      <div className="mx-1 rounded-xl bg-white/5 px-3 py-2.5 ring-1 ring-inset ring-white/10">
        <div className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">Organisation</div>
        <div className="truncate text-sm font-semibold text-white">{me.org.name}</div>
      </div>
    );
  }
  return (
    <div className="relative mx-1">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between gap-2 rounded-xl bg-white/5 px-3 py-2.5 text-left ring-1 ring-inset ring-white/10 transition hover:bg-white/10">
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">Viewing organisation</div>
          <div className="truncate text-sm font-semibold text-white">{cur?.name ?? "Select an organisation"}</div>
        </div>
        <ChevronDown size={16} className={cn("shrink-0 text-slate-400 transition", open && "rotate-180")} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 4 }} exit={{ opacity: 0, y: -4 }} className="absolute inset-x-0 z-30 rounded-xl bg-night-700 p-1.5 shadow-lift ring-1 ring-white/10">
            {orgs.length > 6 && <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" className="mb-1 h-8 w-full rounded-lg bg-white/10 px-2.5 text-xs text-white outline-none placeholder:text-slate-500" />}
            <div className="scrollbar-thin max-h-72 overflow-y-auto">
              {filtered.map((o) => (
                <button key={o.slug} onClick={() => { setOpen(false); nav(`/o/${o.slug}`); }} className={cn("block w-full rounded-lg px-2.5 py-2 text-left text-sm transition hover:bg-white/10", o.slug === current ? "text-brand-400" : "text-slate-200")}>
                  {o.name}{o.city && <span className="ml-1 text-xs text-slate-500">· {o.city}</span>}
                </button>
              ))}
              {!filtered.length && <div className="px-2.5 py-2 text-xs text-slate-400">No organisations yet. Create one in Admin → Organisations.</div>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Freshness() {
  const { data } = useQuery({ queryKey: ["data-status"], queryFn: () => api<any>("/api/data/status"), staleTime: 120_000 });
  const records = data?.records ?? data?.redis?.records;
  const loaded = data?.loaded_at ?? data?.redis?.meta?.loaded_at;
  const ok = data?.ok ?? data?.redis?.ok;
  return (
    <div className="hidden items-center gap-2 rounded-full bg-white px-3 py-1.5 text-xs text-ink-soft ring-1 ring-inset ring-line md:flex" title="Source: CDSCO NSQ alerts in the in-server Redis">
      <span className="relative flex h-2 w-2">
        <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60", ok ? "bg-brand-400" : "bg-rose-400")} />
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", ok ? "bg-brand-500" : "bg-rose-500")} />
      </span>
      <span className="font-semibold">{records != null ? records.toLocaleString("en-IN") : "—"}</span> CDSCO alerts
      <span className="text-ink-faint">· refreshed {timeAgo(loaded)}</span>
    </div>
  );
}

function UserMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const logout = useLogout();
  const nav = useNavigate();
  const initials = (me.name || me.email).split(/[\s@.]/).filter(Boolean).slice(0, 2).map((s) => s[0]?.toUpperCase()).join("");
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2.5 rounded-full py-1 pl-1 pr-3 ring-1 ring-inset ring-line transition hover:bg-white">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-indigo-500 to-brand-600 text-xs font-bold text-white">{initials}</span>
        <span className="hidden text-left leading-tight sm:block">
          <span className="block text-xs font-semibold">{me.name || me.email}</span>
          <span className="block text-[11px] text-ink-muted">{ROLE_LABEL[me.role]}</span>
        </span>
      </button>
      <AnimatePresence>
        {open && (
          <>
            <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
            <motion.div initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 6, scale: 1 }} exit={{ opacity: 0, y: -6 }} className="absolute right-0 z-40 w-60 rounded-2xl bg-white p-1.5 shadow-lift ring-1 ring-line">
              <div className="px-3 py-2 text-xs text-ink-muted">{me.email}</div>
              <button onClick={() => { setOpen(false); nav("/account"); }} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-slate-50"><UserCog size={15} /> Account & password</button>
              <button onClick={async () => { await logout(); nav("/login"); }} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-rose-600 hover:bg-rose-50"><LogOut size={15} /> Sign out</button>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

export function AppShell({ me }: { me: Me }) {
  const loc = useLocation();
  const params = useParams();
  const [mobile, setMobile] = useState(false);
  const slug = params.slug ?? (loc.pathname.startsWith("/o/") ? loc.pathname.split("/")[2] : undefined) ?? (!me.is_platform ? me.org?.slug : undefined);
  const pageKey = useMemo(() => loc.pathname.split("/").slice(0, 4).join("/").replace(/\/(quality|opportunities|eu)\/.+$/, "/$1"), [loc.pathname]);
  useEffect(() => setMobile(false), [loc.pathname]);
  useEffect(() => window.scrollTo({ top: 0 }), [pageKey]);

  const sidebar = (
    <nav className="flex h-full flex-col gap-2 overflow-y-auto bg-night-900 px-3 pb-4 pt-5 scrollbar-thin">
      <Logo />
      <div className="mt-5"><OrgSwitcher me={me} current={slug} /></div>
      {slug && (
        <Section title="Organisation">
          <NavItem to={`/o/${slug}`} end icon={<LayoutDashboard size={17} />}>Overview</NavItem>
          <NavItem to={`/o/${slug}/quality`} icon={<Activity size={17} />}>Quality signals</NavItem>
          <NavItem to={`/o/${slug}/infrastructure`} icon={<Factory size={17} />}>Infrastructure</NavItem>
          <NavItem to={`/o/${slug}/opportunities`} icon={<Sparkles size={17} />}>Patent opportunities</NavItem>
          <NavItem to={`/o/${slug}/eu`} icon={<Globe2 size={17} />}>EU export route</NavItem>
          {(me.is_platform || me.role === "org_admin") && <NavItem to={`/o/${slug}/team`} icon={<Users size={17} />}>Team</NavItem>}
        </Section>
      )}
      {me.is_platform && (
        <Section title="Platform">
          <NavItem to="/admin" end icon={<Gauge size={17} />}>Admin overview</NavItem>
          <NavItem to="/admin/explorer" icon={<Map size={17} />}>All-India NSQ</NavItem>
          <NavItem to="/admin/orgs" icon={<Building2 size={17} />}>Organisations</NavItem>
          <NavItem to="/admin/users" icon={<ShieldCheck size={17} />}>Users & access</NavItem>
          <NavItem to="/admin/jobs" icon={<PlayCircle size={17} />}>Data jobs</NavItem>
          <NavItem to="/admin/audit" icon={<ScrollText size={17} />}>Audit log</NavItem>
        </Section>
      )}
      <div className="mt-auto rounded-xl bg-gradient-to-br from-white/[0.06] to-transparent p-3 text-[11.5px] leading-relaxed text-slate-400 ring-1 ring-inset ring-white/5">
        <div className="mb-1 flex items-center gap-1.5 font-semibold text-slate-300"><FlaskConical size={13} /> Data sources</div>
        CDSCO NSQ alerts · curated patent, regulatory & demand seeds · plant profiles.
      </div>
    </nav>
  );

  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-[264px] shrink-0 lg:block">{sidebar}</aside>
      <AnimatePresence>
        {mobile && (
          <>
            <motion.div className="fixed inset-0 z-40 bg-black/40 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setMobile(false)} />
            <motion.aside className="fixed inset-y-0 left-0 z-50 w-[264px] lg:hidden" initial={{ x: -280 }} animate={{ x: 0 }} exit={{ x: -280 }} transition={{ type: "spring", damping: 30, stiffness: 300 }}>{sidebar}</motion.aside>
          </>
        )}
      </AnimatePresence>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-line bg-canvas/80 px-4 backdrop-blur-md md:px-8">
          <div className="flex items-center gap-3">
            <button onClick={() => setMobile(true)} className="rounded-lg p-2 hover:bg-white lg:hidden"><Menu size={18} /></button>
            <Freshness />
          </div>
          <div className="flex items-center gap-3">
            {me.persona && <span className="hidden items-center gap-1.5 text-xs text-ink-muted sm:flex"><ClipboardList size={14} /> {me.persona} view</span>}
            <UserMenu me={me} />
          </div>
        </header>
        <main className="flex-1">
          <AnimatePresence mode="wait">
            <motion.div key={pageKey} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }} className="mx-auto w-full max-w-[1320px] px-4 py-7 md:px-8">
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
