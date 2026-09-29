import { useEffect, useState } from "react";
import ProtectionPage from "./ProtectionPage";
import type { ActivityEvent, Status } from "./types";

type ProtectionContext = { server: string | null; enabled: boolean | null };

const issueLabels: Record<string, string> = {
  detection_notification_failed: "Detection notification failed",
  detection_notification_unavailable: "Detection channel unavailable",
  delete_failed: "Message deletion failed or was unconfirmed",
  delete_permission_missing: "Message deletion permission missing",
  inspection_unavailable: "Media inspection unavailable",
  gateway_disconnected: "Discord disconnected",
};

function useRuntimeData() {
  const [status, setStatus] = useState<Status | null>(null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    const refresh = async () => {
      try {
        const responses = await Promise.all([
          fetch("/api/status"),
          fetch("/api/activity"),
        ]);
        if (responses.some((response) => !response.ok)) throw new Error();
        const [nextStatus, nextEvents] = await Promise.all(
          responses.map((response) => response.json()),
        );
        setStatus(nextStatus);
        setEvents(nextEvents);
        setError(false);
      } catch {
        setStatus(null);
        setEvents([]);
        setError(true);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => window.clearInterval(timer);
  }, []);
  return { status, events, error };
}

function StatusValue({
  tone,
  children,
}: {
  tone: "good" | "muted";
  children: React.ReactNode;
}) {
  return (
    <span className={`status-value ${tone}`}>
      <span className="status-dot" aria-hidden="true" />
      {children}
    </span>
  );
}

function Overview({
  status,
  events,
  error,
  protection,
}: {
  status: Status | null;
  events: ActivityEvent[];
  error: boolean;
  protection: ProtectionContext;
}) {
  const discordReady = status?.discord.state === "ready";
  const issue =
    events[0]?.category === "Error"
      ? (issueLabels[events[0].code] ?? events[0].code.replaceAll("_", " "))
      : null;

  return (
    <section className="overview-column" aria-labelledby="overview-heading">
      <div className="column-heading">
        <h1 id="overview-heading">Overview</h1>
      </div>
      <dl className="status-surface">
        <div>
          <dt>Bot</dt>
          <dd>
            <StatusValue tone={status ? "good" : "muted"}>
              {status ? "Online" : error ? "Offline" : "Connecting"}
            </StatusValue>
          </dd>
        </div>
        <div>
          <dt>Discord</dt>
          <dd>
            <StatusValue tone={discordReady ? "good" : "muted"}>
              {discordReady
                ? "Connected"
                : (status?.discord.state ?? "Unavailable")}
            </StatusValue>
          </dd>
        </div>
        <div>
          <dt>Protection</dt>
          <dd>
            <StatusValue tone={protection.enabled && !error ? "good" : "muted"}>
              {error
                ? "Unavailable"
                : protection.enabled === null
                  ? "Unknown"
                  : protection.enabled
                    ? "Enabled"
                    : "Disabled"}
            </StatusValue>
          </dd>
        </div>
        <div>
          <dt>Server</dt>
          <dd>
            {error
              ? "Unavailable"
              : (protection.server ?? "No connected server")}
          </dd>
        </div>
      </dl>
      {!error && issue && (
        <p className="operational-issue" role="status">
          <span className="status-dot" aria-hidden="true" />
          <strong>Operational issue</strong>
          <span>{issue}</span>
        </p>
      )}
    </section>
  );
}

export default function App() {
  const [protection, setProtection] = useState<ProtectionContext>({
    server: null,
    enabled: null,
  });
  const { status, events, error } = useRuntimeData();

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <strong>MediaGuard</strong>
          <small>Operator console</small>
        </div>
        <span
          className={`topbar-status ${status ? "good" : error ? "error" : "muted"}`}
        >
          <span className="status-dot" aria-hidden="true" />
          {status ? "Online" : error ? "Offline" : "Connecting"}
        </span>
      </header>
      <main className="console">
        {error && (
          <p className="inline-alert" role="alert">
            Operator backend unavailable. Start MediaGuard to reconnect.
          </p>
        )}
        <div className="console-columns">
          <Overview
            status={status}
            events={events}
            error={error}
            protection={protection}
          />
          <ProtectionPage
            discordState={status?.discord.state ?? "unavailable"}
            backendAvailable={!error}
            onContextChange={setProtection}
          />
        </div>
      </main>
    </div>
  );
}
