import { motion } from "motion/react";
import type { ReactNode } from "react";

const FACTS = [
  { k: "5,600+", v: "CDSCO NSQ alerts analysed" },
  { k: "26", v: "Off-patent & LOE molecules scored" },
  { k: "10", v: "EU export checks per molecule" },
];

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden bg-night-900 lg:block">
        <motion.div className="absolute -left-24 -top-24 h-[480px] w-[480px] rounded-full bg-brand-500/25 blur-3xl" animate={{ x: [0, 40, 0], y: [0, 30, 0] }} transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }} />
        <motion.div className="absolute -bottom-32 right-0 h-[420px] w-[420px] rounded-full bg-indigo-500/25 blur-3xl" animate={{ x: [0, -30, 0], y: [0, -40, 0] }} transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }} />
        <svg className="absolute inset-0 h-full w-full opacity-[0.07]" xmlns="http://www.w3.org/2000/svg"><defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="white" strokeWidth="1" /></pattern></defs><rect width="100%" height="100%" fill="url(#grid)" /></svg>
        <div className="relative flex h-full flex-col justify-between p-12">
          <div className="flex items-center gap-2.5">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700"><svg viewBox="0 0 32 32" className="h-5 w-5"><path d="M8 23V9l8 9 8-9v14" stroke="white" strokeWidth="3.2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg></div>
            <span className="font-display text-lg font-extrabold text-white">NSQ Intelligence</span>
          </div>
          <div>
            <motion.h1 initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7 }} className="max-w-xl font-display text-[42px] font-extrabold leading-[1.08] tracking-tight text-white">
              See why your batches get flagged — and where your plants can go next.
            </motion.h1>
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3, duration: 0.7 }} className="mt-5 max-w-lg text-[15px] leading-relaxed text-slate-400">
              CDSCO quality signals, plant capability, patent expiries and the EU export route in one view — for manufacturers and their QA, regulatory and leadership teams.
            </motion.p>
            <div className="mt-10 grid max-w-xl grid-cols-3 gap-4">
              {FACTS.map((f, i) => (
                <motion.div key={f.v} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.45 + i * 0.1 }} className="rounded-2xl bg-white/5 p-4 ring-1 ring-inset ring-white/10">
                  <div className="font-display text-2xl font-extrabold text-white">{f.k}</div>
                  <div className="mt-1 text-xs leading-snug text-slate-400">{f.v}</div>
                </motion.div>
              ))}
            </div>
          </div>
          <div className="text-xs text-slate-500">Data: CDSCO Not-of-Standard-Quality alerts, Jan 2021 onwards.</div>
        </div>
      </div>
      <div className="grid place-items-center px-6 py-12">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="w-full max-w-sm">{children}</motion.div>
      </div>
    </div>
  );
}
