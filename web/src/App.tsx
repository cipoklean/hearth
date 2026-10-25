import { useEffect } from "react";
import { Icon } from "./components/Icon";
import { ErrorNote, Loading, ToastProvider } from "./components/ui";
import { Link, navigate, usePath } from "./router";
import { HomeProvider, useHome } from "./state";
import { Landing } from "./pages/Landing";
import { Shelf } from "./pages/Shelf";
import { Setup } from "./pages/Setup";
import { ResidentPage } from "./pages/Resident";
import { WeekPage } from "./pages/Week";
import { GroupPage } from "./pages/Group";
import { CheckPage } from "./pages/Check";
import { PrivacyPage } from "./pages/Privacy";

const NAV = [
  { to: "/", label: "Residents", icon: "people", match: (p: string) => p === "/" || p.startsWith("/r/") },
  { to: "/group", label: "Group activity", icon: "sparkle", match: (p: string) => p.startsWith("/group") },
  { to: "/check", label: "Taste check", icon: "list", match: (p: string) => p.startsWith("/check") },
  { to: "/privacy", label: "Privacy", icon: "shield", match: (p: string) => p.startsWith("/privacy") },
];

function Shell() {
  const path = usePath();
  const { home, residents, error, refresh } = useHome();
  const hasHome = !!residents && residents.length > 0;
  const landing = path === "/welcome" || (path === "/" && residents !== null && !hasHome);
  const setup = path.startsWith("/setup");

  useEffect(() => {
    const titles: Record<string, string> = { "/group": "Group activity", "/check": "Taste check", "/privacy": "Privacy", "/setup": "Meet a resident" };
    const t = Object.entries(titles).find(([k]) => path.startsWith(k))?.[1];
    document.title = t ? `${t} · Hearth` : "Hearth · taste-aware care planning";
  }, [path]);

  let page: React.ReactNode;
  if (error && !residents) page = <main className="page"><ErrorNote error={error} retry={refresh} /></main>;
  else if (residents === null) page = <main className="page"><Loading label="Opening the planner…" /></main>;
  else if (landing) page = <Landing />;
  else if (setup) page = <Setup />;
  else if (path === "/") page = <Shelf />;
  else if (path.startsWith("/r/")) {
    const [, , id, sub] = path.split("/");
    page = sub === "week" ? <WeekPage id={id} /> : <ResidentPage id={id} />;
  } else if (path.startsWith("/group")) page = <GroupPage />;
  else if (path.startsWith("/check")) page = <CheckPage />;
  else if (path.startsWith("/privacy")) page = <PrivacyPage />;
  else page = <main className="page"><h1 className="display">Page not found</h1><Link to="/" className="btn">Back to residents</Link></main>;

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      {!landing && (
        <header className="masthead no-print">
          <Link to="/" className="wordmark" aria-label="Hearth, residents">
            <span className="wordmark__flame" aria-hidden><Icon name="flame" size={26} /></span>
            <span className="wordmark__text">Hearth</span>
          </Link>
          {home?.name && (
            <span className="masthead__home">
              {home.name}{home.city ? <span className="muted"> · {home.city}</span> : null}
              {home.demo && <span className="sample-pill">Sample home</span>}
              {home.demo && !setup && <Link to="/setup" className="masthead__own">Start your own →</Link>}
            </span>
          )}
          {hasHome && !setup && (
            <nav className="tabs" aria-label="Main">
              {NAV.map((n) => (
                <Link key={n.to} to={n.to} className={"tab" + (n.match(path) ? " is-active" : "")} aria-current={n.match(path) ? "page" : undefined}>
                  <Icon name={n.icon} size={20} />
                  <span>{n.label}</span>
                </Link>
              ))}
            </nav>
          )}
          {setup && <button className="btn btn--ghost btn--sm masthead__exit" onClick={() => navigate(hasHome ? "/" : "/welcome")}>Leave setup</button>}
        </header>
      )}
      <div id="main" tabIndex={-1}>{page}</div>
      {!landing && home?.mock && (
        <p className="mockline no-print">Offline demo mode: names and scores come from Hearth's invented test catalogue, not from Qloo.</p>
      )}
    </>
  );
}

export function App() {
  return (
    <ToastProvider>
      <HomeProvider>
        <Shell />
      </HomeProvider>
    </ToastProvider>
  );
}
