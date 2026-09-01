import * as React from "react";
import { cn } from "../../lib/utils";

// Lightweight scroll-area: a styled overflow container. The Streamlit app
// uses a fixed max-height + styled scrollbar (see .mq-issue-list in
// palette.py); this mirrors that without pulling a scroll primitive dep.
export const ScrollArea = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, children, style, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("overflow-y-auto", className)}
      style={{ scrollbarWidth: "thin", ...style }}
      {...props}
    >
      {children}
    </div>
  ),
);
ScrollArea.displayName = "ScrollArea";