import { useEffect, useLayoutEffect, useState } from "react";
import { Icon } from "./Icon";

export interface TourStep { target: string; title: string; body: string }

const KEY = "hearth.tour.done";
export const tourDone = () => localStorage.getItem(KEY) === "1";

/** A short, dismissible coach-mark tour. Highlights [data-tour=target]; remembered in localStorage. */
export function Tour({ steps, onClose }: { steps: TourStep[]; onClose?: () => void }) {
  const [i, setI] = useState(0);
  const [open, setOpen] = useState(!tourDone());
  const [rect, setRect] = useState<DOMRect | null>(null);
  const step = steps[i];

  useLayoutEffect(() => {
    if (!open) return;
    const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
    if (!el) { setRect(null); return; }
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    const upd = () => setRect(el.getBoundingClientRect());
    upd();
    const t = setTimeout(upd, 400);
    addEventListener("resize", upd);
    addEventListener("scroll", upd, true);
    return () => { clearTimeout(t); removeEventListener("resize", upd); removeEventListener("scroll", upd, true); };
  }, [i, open, step?.target]);

  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  });

  function close() {
    localStorage.setItem(KEY, "1");
    setOpen(false);
    onClose?.();
  }
  if (!open || !step) return null;

  const pad = 10;
  return (
    <div className="tour no-print">
      {rect && (
        <div className="tour__ring" aria-hidden
          style={{ top: rect.top - pad, left: rect.left - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 }} />
      )}
      <div className="tour__card" role="dialog" aria-labelledby="tour-title" aria-describedby="tour-body">
        <span className="tour__count">Step {i + 1} of {steps.length}</span>
        <h2 id="tour-title">{step.title}</h2>
        <p id="tour-body">{step.body}</p>
        <div className="tour__actions">
          <button className="btn btn--ghost btn--sm" onClick={close}>Skip tour</button>
          <span className="tour__dots" aria-hidden>{steps.map((_, j) => <i key={j} className={j === i ? "on" : ""} />)}</span>
          {i < steps.length - 1 ? (
            <button className="btn btn--sm" onClick={() => setI(i + 1)} autoFocus>Next <Icon name="arrow" size={18} /></button>
          ) : (
            <button className="btn btn--sm" onClick={close} autoFocus>Got it</button>
          )}
        </div>
      </div>
    </div>
  );
}
