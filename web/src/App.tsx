import { useEffect, useState } from "react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import DetectionsPage from "./DetectionsPage";
import { utcTime } from "./format";
import ProtectionPage from "./ProtectionPage";
import type { ActivityEvent, Detection, Status } from "./types";

type Section =
  "Overview" | "Protection" | "Detections" | "Activity" | "Settings";
const sections: Section[] = [
  "Overview",
  "Protection",
  "Detections",
  "Activity",
  "Settings",
];

const activityLabels: Record<string, string> = {
  gateway_ready: "Bot connected",
  gateway_disconnected: "Bot disconnected",
  gateway_resumed: "Bot reconnected",
  protection_configuration_saved: "Protection configuration saved",
  embed_rule_saved: "Blocked phrase saved",
  embed_rule_deleted: "Blocked phrase deleted",
  message_removed: "Detection deleted",
  detection_notification_failed: "Detection notification failed",
  detection_notification_unavailable: "Detection notification unavailable",
  delete_failed: "Deletion failed or unconfirmed",
  delete_permission_missing: "Deletion permission missing",
  inspection_unavailable: "Inspection unavailable",
  runtime_started: "MediaGuard started",
  runtime_stopped: "MediaGuard stopped",
};

function useRuntimeData() {
  const [status, setStatus] = useState<Status | null>(null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    const refresh = async () => {
      try {
        const responses = await Promise.all([
          fetch("/api/status"),
          fetch("/api/activity"),
          fetch("/api/detections"),
        ]);
        if (responses.some((response) => !response.ok)) throw new Error();
        const [nextStatus, nextEvents, nextDetections] = await Promise.all(
          responses.map((response) => response.json()),
        );
        setStatus(nextStatus);
        setEvents(nextEvents);
        setDetections(nextDetections);
        setError(false);
      } catch {
        setError(true);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => window.clearInterval(timer);
  }, []);
  return { status, events, detections, error };
}

function ActivityList({ events }: { events: ActivityEvent[] }) {
  if (!events.length)
    return <p className="empty-state">No activity has been recorded yet.</p>;
  return (
    <ol className="activity-list">
      {events.map((event, index) => (
        <li key={`${event.at}-${index}`}>
          <Badge
            variant={event.category === "Error" ? "destructive" : "outline"}
          >
            {event.category}
          </Badge>
          <span>
            {activityLabels[event.code] ?? event.code.replaceAll("_", " ")}
          </span>
          <time dateTime={event.at}>
            {new Date(event.at).toLocaleTimeString()}
          </time>
        </li>
      ))}
    </ol>
  );
}

function Overview({
  status,
  events,
  onActivity,
}: {
  status: Status | null;
  events: ActivityEvent[];
  onActivity: () => void;
}) {
  const connected = status?.discord.state === "ready";
  return (
    <div className="content">
      <div className="page-heading">
        <h1>Overview</h1>
        <p>Connection and retained detection history.</p>
      </div>
      <div className="overview-grid">
        <Card size="sm">
          <CardHeader>
            <CardTitle>Bot</CardTitle>
          </CardHeader>
          <CardContent className="overview-value">
            <Badge variant={connected ? "secondary" : "outline"}>
              {connected ? "Online" : "Offline"}
            </Badge>
            <p>
              {connected
                ? `${status?.discord.guild_count ?? 0} connected servers`
                : "Discord connection unavailable"}
            </p>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Audio blocked</CardTitle>
          </CardHeader>
          <CardContent className="overview-value">
            <strong>{status?.detections.audio_blocked ?? "—"}</strong>
            <p>Confirmed deletions in retained history</p>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Recent detection</CardTitle>
          </CardHeader>
          <CardContent className="overview-value">
            <strong className="overview-time">
              {status?.detections.recent_detection_at
                ? utcTime(status.detections.recent_detection_at)
                : "No detections yet"}
            </strong>
            <p>Most recent confirmed deletion</p>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Storage</CardTitle>
          </CardHeader>
          <CardContent className="overview-value">
            <Badge variant="outline">{status?.database ?? "Unknown"}</Badge>
            <p>Metadata-only local audit</p>
          </CardContent>
        </Card>
      </div>
      <Card size="sm" className="overview-activity">
        <CardHeader className="card-heading-line">
          <CardTitle>Recent activity</CardTitle>
          <Button variant="ghost" size="sm" onClick={onActivity}>
            View all
          </Button>
        </CardHeader>
        <CardContent className="activity-content">
          <ActivityList events={events.slice(0, 6)} />
        </CardContent>
      </Card>
    </div>
  );
}

export default function App() {
  const [section, setSection] = useState<Section>("Overview");
  const { status, events, detections, error } = useRuntimeData();
  const connected = status?.discord.state === "ready";

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
            <Button
              key={item}
              type="button"
              variant="ghost"
              size="sm"
              className={section === item ? "nav-item active" : "nav-item"}
              aria-current={section === item ? "page" : undefined}
              onClick={() => setSection(item)}
            >
              {item}
            </Button>
          ))}
        </nav>
        <div className="sidebar-foot">Local operator</div>
      </aside>
      <main>
        <header className="topbar">
          <span>MediaGuard / {section}</span>
          <Badge
            variant={connected ? "secondary" : "outline"}
            className={connected ? "connection connected" : "connection"}
          >
            {connected ? "Bot connected" : "Bot offline"}
          </Badge>
        </header>
        {error && (
          <div className="api-error" role="alert">
            The operator backend is unavailable. Start MediaGuard and refresh
            this page.
          </div>
        )}
        {section === "Overview" && (
          <Overview
            status={status}
            events={events}
            onActivity={() => setSection("Activity")}
          />
        )}
        <div hidden={section !== "Protection"}>
          <ProtectionPage
            discordState={status?.discord.state ?? "unavailable"}
          />
        </div>
        {section === "Detections" && <DetectionsPage detections={detections} />}
        {section === "Activity" && (
          <div className="content">
            <div className="page-heading">
              <h1>Activity</h1>
              <p>Operational events from this runtime.</p>
            </div>
            <Card size="sm">
              <CardContent className="activity-content">
                <ActivityList events={events} />
              </CardContent>
            </Card>
          </div>
        )}
        {section === "Settings" && (
          <div className="content">
            <div className="page-heading">
              <h1>Settings</h1>
              <p>Local runtime configuration.</p>
            </div>
            <Card size="sm">
              <CardContent className="settings-content">
                <dl>
                  <div>
                    <dt>Discord connection</dt>
                    <dd>{status?.discord.state ?? "Unknown"}</dd>
                  </div>
                  <div>
                    <dt>Detection retention</dt>
                    <dd>{status?.detection_retention_days ?? "—"} days</dd>
                  </div>
                </dl>
                <p>
                  The bot token belongs in local secrets.env. Protection is
                  configured per server on the Protection page. MediaGuard does
                  not retain blocked audio.
                </p>
              </CardContent>
            </Card>
          </div>
        )}
      </main>
    </div>
  );
}
