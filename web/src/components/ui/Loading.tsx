// Loading feedback that never hides content.
//  * <TopProgress/>: one thin bar across the top of the window whenever data is on its way — a first load or a
//    change of filters / parameters. Background refreshes of data already on screen don't trigger it.
//  * <LoadingEdge active/>: the same light, on the top edge of one component (its parent must be `relative`).
import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";

// A query is "loading for the user" while it fetches data it doesn't have yet (status pending): first loads, and
// new parameters shown over the previous result with keepPreviousData. Interval polls of loaded data are excluded.
const userVisible = (q: any) => q.state.fetchStatus === "fetching" && q.state.status === "pending";

export function TopProgress() {
  const busy = useIsFetching({ predicate: userVisible }) + useIsMutating() > 0;
  const [shown, setShown] = useState(false);
  const [pct, setPct] = useState(0);
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    if (busy) {
      // wait 120 ms so instant responses don't flash the bar
      const t = setTimeout(() => {
        setDone(false);
        setShown(true);
        setPct(8);
        clearInterval(timer.current);
        // trickle toward 90%: fast at first, slower as it goes — it never claims to be finished
        timer.current = setInterval(() => setPct((p) => (p < 90 ? p + (90 - p) * 0.08 : p)), 180);
      }, 120);
      return () => clearTimeout(t);
    }
    if (shown) {
      clearInterval(timer.current);
      setPct(100);
      setDone(true);
      const t = setTimeout(() => { setShown(false); setPct(0); setDone(false); }, 380);
      return () => clearTimeout(t);
    }
  }, [busy]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => clearInterval(timer.current), []);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-x-0 top-0 z-[200] h-[3px]">
      <div
        className={cn("relative h-full origin-left rounded-r-full bg-gradient-to-r from-brand-400 via-brand-500 to-emerald-300",
          "shadow-[0_0_10px_rgba(16,185,150,0.7),0_0_4px_rgba(16,185,150,0.9)] transition-[width,opacity] ease-out",
          done ? "duration-300" : "duration-200", shown ? "opacity-100" : "opacity-0")}
        style={{ width: `${pct}%` }}>
        {/* the moving highlight at the head of the bar */}
        {shown && !done && <span className="absolute right-0 top-1/2 h-[7px] w-24 -translate-y-1/2 rounded-full bg-white/40 blur-[3px] nsq-pulse" />}
      </div>
    </div>
  );
}

export function LoadingEdge({ active, className }: { active: boolean; className?: string }) {
  return (
    <div aria-hidden className={cn("pointer-events-none absolute inset-x-0 top-0 z-10 h-[2px] overflow-hidden rounded-t-[inherit] transition-opacity duration-300",
      active ? "opacity-100" : "opacity-0", className)}>
      <div className="nsq-sweep h-full w-1/3 bg-gradient-to-r from-transparent via-brand-500 to-transparent" />
    </div>
  );
}
