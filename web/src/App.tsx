import { useEffect, useState } from "react";

type Section = "Overview" | "Cases" | "Rules" | "Activity" | "Settings";
type Status = {
  app: string;
  uptime_seconds: number;
  database: string;
  discord: {
    state: string;
    gateway: string;
    guild_count: number | null;
    ready_at: string | null;
    reconnect_count: number;
  };
  services: { name: string; state: string }[];
};
type Event = { at: string; category: string; code: string };
const sections: Section[] = [
  "Overview",
  "Cases",
  "Rules",
  "Activity",
  "Settings",
];

function useData() {
  const [status, setStatus] = useState<Status | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    const refresh = async () => {
      try {
        const [s, a] = await Promise.all([
          fetch("/api/status"),
          fetch("/api/activity"),
        ]);
        if (!s.ok || !a.ok) throw new Error("API unavailable");
        setStatus(await s.json());
        setEvents(await a.json());
        setError(false);
      } catch {
        setError(true);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => window.clearInterval(timer);
  }, []);
  return { status, events, error };
}

function ActivityList({ events }: { events: Event[] }) {
  return events.length ? (
    <ol className="activity-list">
      {events.map((event, index) => (
        <li key={`${event.at}-${index}`}>
          <span className="event-dot" />
          <span>
            <strong>{event.category}</strong>
            <small>{event.code.replaceAll("_", " ")}</small>
          </span>
          <time>{new Date(event.at).toLocaleTimeString()}</time>
        </li>
      ))}
    </ol>
  ) : (
    <p className="empty">No activity has been recorded yet.</p>
  );
}

function duration(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export default function App() {
  const [section, setSection] = useState<Section>("Overview");
  const { status, events, error } = useData();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            M
          </span>
          <div>
            <strong>MediaGuard</strong>
            <small>Operator console</small>
          </div>
        </div>
        <nav aria-label="Main navigation">
          {sections.map((item) => (
            <button
              key={item}
              className={section === item ? "active" : ""}
              onClick={() => setSection(item)}
            >
              {item}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="live-dot" />
          Local operator
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>MediaGuard / {section}</span>
          <span className="top-status">
            <span
              className={
                status?.discord.state === "ready" ? "live-dot" : "idle-dot"
              }
            />
            {status?.discord.state === "ready"
              ? "Bot connected"
              : "Bot offline"}
          </span>
        </header>
        {error && (
          <div className="error" role="alert">
            The operator backend is unavailable. Start MediaGuard and refresh
            this page.
          </div>
        )}
        {section === "Overview" && (
          <div className="content">
            <div className="page-heading">
              <h1>Overview</h1>
              <p>Runtime health and recent service activity.</p>
            </div>
            <div className="overview-grid">
              <section className="primary-panel">
                <div className="panel-heading">
                  <h2>System status</h2>
                  <span className="subtle">Live runtime</span>
                </div>
                <dl className="status-list">
                  <div>
                    <dt>MediaGuard</dt>
                    <dd>{status ? "Running" : "Unavailable"}</dd>
                  </div>
                  <div>
                    <dt>Discord bot</dt>
                    <dd>{status?.discord.state ?? "Unknown"}</dd>
                  </div>
                  <div>
                    <dt>Gateway</dt>
                    <dd>{status?.discord.gateway ?? "Unknown"}</dd>
                  </div>
                  <div>
                    <dt>Connected guilds</dt>
                    <dd>{status?.discord.guild_count ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Database</dt>
                    <dd>{status?.database ?? "Unknown"}</dd>
                  </div>
                  <div>
                    <dt>Uptime</dt>
                    <dd>{status ? duration(status.uptime_seconds) : "—"}</dd>
                  </div>
                </dl>
              </section>
              <section className="activity-panel">
                <div className="panel-heading">
                  <h2>Recent activity</h2>
                  <button
                    className="text-button"
                    onClick={() => setSection("Activity")}
                  >
                    View all
                  </button>
                </div>
                <ActivityList events={events.slice(0, 6)} />
              </section>
            </div>
            <section className="services">
              <h2>Services</h2>
              {status?.services.map((service) => (
                <div className="service-row" key={service.name}>
                  <span>{service.name}</span>
                  <strong>{service.state}</strong>
                </div>
              )) ?? <p className="empty">Status unavailable.</p>}
            </section>
          </div>
        )}
        {(section === "Cases" || section === "Rules") && (
          <div className="content">
            <div className="page-heading">
              <h1>{section}</h1>
              <p>
                {section === "Cases"
                  ? "Moderation case management"
                  : "Deterministic inspection rules"}
              </p>
            </div>
            <div className="placeholder">
              <span className="placeholder-icon" aria-hidden="true">
                ◇
              </span>
              <h2>Not implemented yet</h2>
              <p>
                {section} will be built in a later implementation phase. No
                moderation behavior is active in this bootstrap.
              </p>
            </div>
          </div>
        )}
        {section === "Activity" && (
          <div className="content">
            <div className="page-heading">
              <h1>Activity</h1>
              <p>Service lifecycle events recorded by this runtime.</p>
            </div>
            <section className="full-panel">
              <ActivityList events={events} />
            </section>
          </div>
        )}
        {section === "Settings" && (
          <div className="content">
            <div className="page-heading">
              <h1>Settings</h1>
              <p>Current local configuration.</p>
            </div>
            <section className="full-panel settings">
              <div>
                <span>Discord connection</span>
                <strong>{status?.discord.state ?? "Unknown"}</strong>
              </div>
              <p>
                Configure the bot in config.json and set its own token in
                secrets.env. Settings are edited locally; this dashboard has no
                write controls yet.
              </p>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
