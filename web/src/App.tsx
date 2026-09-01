// Router + auth gate. Session-only: the gate reads the zustand store; a
// signed-out user hitting a protected route is redirected to /sign-in.
// Routes: /sign-in, /dashboard, /diagnostics/:issueId. The "/diagnostics/random"
// path is a nav-tab entry point that Diagnostics resolves to a random issue
// from the cached dashboard issue list.

import { Navigate, Route, Routes } from "react-router-dom";
import { Header } from "./components/layout/Header";
import { SignIn } from "./pages/SignIn";
import { Dashboard } from "./pages/Dashboard";
import { Diagnostics } from "./pages/Diagnostics";
import { useSession } from "./state/session";

function Protected({ children }: { children: React.ReactNode }) {
  const signedIn = useSession((s) => s.signedIn);
  if (!signedIn) return <Navigate to="/sign-in" replace />;
  return (
    <div className="min-h-screen">
      <Header />
      {children}
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route
        path="/dashboard"
        element={
          <Protected>
            <Dashboard />
          </Protected>
        }
      />
      <Route
        path="/diagnostics/:issueId"
        element={
          <Protected>
            <Diagnostics />
          </Protected>
        }
      />
      <Route path="*" element={<Navigate to="/sign-in" replace />} />
    </Routes>
  );
}