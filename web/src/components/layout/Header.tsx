// App header — the Q-engine wordmark (bioicon mark + text, no raster logo)
// on the left, the signed-in user pill + sign-out on the right. Mirrors the
// Streamlit mq-wordmark / mq-user-pill in palette.py.

import { useNavigate } from "react-router-dom";
import { QmarkIcon, FactoryIcon } from "../icons/BioIcon";
import { Button } from "../ui/button";
import { useSession } from "../../state/session";

export function Header() {
  const navigate = useNavigate();
  const { signedIn, tenant, persona, signOut } = useSession();

  return (
    <header className="flex items-center justify-between border-b border-border px-6 py-3">
      <button
        className="flex items-center gap-2 text-lg font-bold tracking-tight text-foreground"
        onClick={() => navigate(signedIn ? "/dashboard" : "/sign-in")}
      >
        <QmarkIcon size={22} className="text-primary" />
        <span>Q-engine</span>
      </button>

      {signedIn && tenant && persona && (
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-foreground">
            <FactoryIcon size={14} className="text-primary" />
            <span className="font-semibold">{persona}</span>
            <span className="text-muted-foreground">·</span>
            <span className="text-foreground/80">{tenant.canonical}</span>
            <span className="text-muted-foreground">— {tenant.city}</span>
          </span>
          <Button variant="outline" size="sm" onClick={() => { signOut(); navigate("/sign-in"); }}>
            Sign out
          </Button>
        </div>
      )}
    </header>
  );
}