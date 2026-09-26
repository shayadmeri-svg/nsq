import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { useMe } from "./lib/session";
import { Login } from "./pages/auth/Login";
import { AcceptInvite } from "./pages/auth/AcceptInvite";
import { Account } from "./pages/Account";
import { OrgOverview } from "./pages/org/Overview";
import { Quality } from "./pages/org/Quality";
import { Infrastructure } from "./pages/org/Infrastructure";
import { Opportunities } from "./pages/org/Opportunities";
import { EuExport } from "./pages/org/EuExport";
import { Team } from "./pages/org/Team";
import { AdminOverview } from "./pages/admin/AdminOverview";
import { Orgs } from "./pages/admin/Orgs";
import { Users } from "./pages/admin/Users";
import { Jobs } from "./pages/admin/Jobs";
import { Audit } from "./pages/admin/Audit";
import { Explorer } from "./pages/admin/Explorer";

function Splash() {
  return (
    <div className="grid h-full place-items-center">
      <div className="h-8 w-8 animate-spin rounded-full border-[3px] border-brand-500 border-t-transparent" />
    </div>
  );
}

function Home() {
  const { data: me } = useMe();
  if (!me) return <Navigate to="/login" replace />;
  if (me.is_platform) return <Navigate to="/admin" replace />;
  if (me.org) return <Navigate to={`/o/${me.org.slug}`} replace />;
  return <Navigate to="/account" replace />;
}

function Protected({ platform }: { platform?: boolean }) {
  const { data: me, isLoading } = useMe();
  const loc = useLocation();
  if (isLoading) return <Splash />;
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />;
  if (me.must_change_password && loc.pathname !== "/account") return <Navigate to="/account?first=1" replace />;
  if (platform && !me.is_platform && !(loc.pathname.startsWith("/admin/users") && me.permissions.manage_users)) return <Navigate to="/" replace />;
  return <AppShell me={me} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/invite/:token" element={<AcceptInvite />} />
      <Route element={<Protected />}>
        <Route path="/" element={<Home />} />
        <Route path="/account" element={<Account />} />
        <Route path="/o/:slug" element={<OrgOverview />} />
        <Route path="/o/:slug/quality" element={<Quality />} />
        <Route path="/o/:slug/quality/:issueId" element={<Quality />} />
        <Route path="/o/:slug/infrastructure" element={<Infrastructure />} />
        <Route path="/o/:slug/opportunities" element={<Opportunities />} />
        <Route path="/o/:slug/opportunities/:molecule" element={<Opportunities />} />
        <Route path="/o/:slug/eu" element={<EuExport />} />
        <Route path="/o/:slug/eu/:molecule" element={<EuExport />} />
        <Route path="/o/:slug/team" element={<Team />} />
      </Route>
      <Route element={<Protected platform />}>
        <Route path="/admin" element={<AdminOverview />} />
        <Route path="/admin/orgs" element={<Orgs />} />
        <Route path="/admin/users" element={<Users />} />
        <Route path="/admin/jobs" element={<Jobs />} />
        <Route path="/admin/audit" element={<Audit />} />
        <Route path="/admin/explorer" element={<Explorer />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
