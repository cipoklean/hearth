// Hand-drawn-feel line icons (single stroke, round caps). Decorative unless a label is given.
const P: Record<string, string> = {
  flame: "M12 3c2 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-5 3-7 .5 2 1.5 3 2.5 3.5C11 7.5 11.5 5 12 3z",
  note: "M9 18V6l10-2v12M9 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0zM19 16a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
  film: "M4 5h16v14H4zM8 5v14M16 5v14M4 9h4M4 15h4M16 9h4M16 15h4",
  book: "M4 5c3-1 5-1 8 1 3-2 5-2 8-1v14c-3-1-5-1-8 1-3-2-5-2-8-1zM12 6v14",
  tv: "M4 8h16v11H4zM9 3l3 4 3-4",
  pin: "M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  plate: "M12 19a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 4v5M3 9v11M21 4c-1.5 0-2 2-2 5h2v11",
  spoon: "M12 3c2 0 3 2 3 4.5S14 12 12 12s-3-2-3-4.5S10 3 12 3zM12 12v9",
  salt: "M8 9h8l-1 12H9zM9 9c0-3 1-6 3-6s3 3 3 6M11 13h.01M13 15h.01M11 17h.01",
  cube: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5",
  leaf: "M5 19c0-9 6-14 15-14 0 9-5 15-14 15M5 19l7-7",
  wheel: "M10 4a1.5 1.5 0 1 0 0-.01M10 7v6h6l2 5M10 10h5M8 10.5a5 5 0 1 0 6.5 6.5",
  ear: "M8 9a4 4 0 1 1 8 0c0 3-3 4-3 7a2.5 2.5 0 0 1-5 0M11 9a1 1 0 1 1 2 0",
  quiet: "M4 10v4h3l4 4V6L7 10zM16 9l5 6M21 9l-5 6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  heart: "M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",
  check: "M5 12.5l4.5 4.5L19 7",
  cross: "M6 6l12 12M18 6L6 18",
  swap: "M7 7h11l-3-3M17 17H6l3 3",
  print: "M7 9V3h10v6M7 17H4v-7h16v7h-3M7 14h10v7H7z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  plus: "M12 5v14M5 12h14",
  arrow: "M5 12h14M13 6l6 6-6 6",
  back: "M19 12H5M11 6l-6 6 6 6",
  people: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20c.5-4 3-6 6.5-6s6 2 6.5 6M16 11a3 3 0 1 0 0-6M17.5 14c2.5.5 4 2.5 4 6",
  list: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  thumbUp: "M7 11v9H4v-9zM7 11l4-8c1.5 0 2.5 1 2.5 2.5V9h5a2 2 0 0 1 2 2.3l-1.2 6.5A2.5 2.5 0 0 1 16.8 20H7",
  thumbDown: "M7 13V4H4v9zM7 13l4 8c1.5 0 2.5-1 2.5-2.5V15h5a2 2 0 0 0 2-2.3l-1.2-6.5A2.5 2.5 0 0 0 16.8 4H7",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5h.01",
  sparkle: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6",
  calendar: "M4 6h16v15H4zM4 10h16M8 3v5M16 3v5",
  tea: "M4 9h12v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM16 10h2a2 2 0 0 1 0 4h-2M8 3c0 2 2 2 2 4M12 3c0 2 2 2 2 4",
};

export function Icon({ name, size = 22, label, className }: { name: string; size?: number; label?: string; className?: string }) {
  return (
    <svg
      className={"icon " + (className || "")}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      <path d={P[name] || P.info} />
    </svg>
  );
}
