import { useEffect, useState } from "react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./components/ui/select";
import { Switch } from "./components/ui/switch";
import type { Guild, Protection, ProtectionDraft } from "./types";
import EmbedRules from "./EmbedRules";

function draftOf(value: Protection): ProtectionDraft {
  return {
    enabled: value.enabled,
    channel_ids: value.channel_ids,
    notifications_enabled: value.notifications_enabled,
    detection_channel_id: value.detection_channel_id,
  };
}

export default function ProtectionPage({
  discordState,
  backendAvailable,
  onContextChange,
}: {
  discordState: string;
  backendAvailable: boolean;
  onContextChange: (value: {
    server: string | null;
    enabled: boolean | null;
  }) => void;
}) {
  const [guilds, setGuilds] = useState<Guild[]>([]);
  const [guildId, setGuildId] = useState("");
  const [saved, setSaved] = useState<Protection | null>(null);
  const [draft, setDraft] = useState<ProtectionDraft | null>(null);
  const [channelMode, setChannelMode] = useState<"all" | "selected">("all");
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{
    kind: "error" | "success";
    text: string;
  } | null>(null);

  async function refreshGuilds() {
    try {
      const response = await fetch("/api/guilds");
      if (!response.ok) throw new Error();
      const available = (await response.json()) as Guild[];
      setGuilds(available);
      setGuildId((current) =>
        available.some((item) => item.id === current)
          ? current
          : (available[0]?.id ?? ""),
      );
    } catch {
      setFeedback({
        kind: "error",
        text: "Could not load connected servers. Try refreshing channels.",
      });
    }
  }

  useEffect(() => {
    if (!backendAvailable) return;
    void refreshGuilds();
  }, [discordState, backendAvailable]);

  useEffect(() => {
    if (!guildId) return;
    const controller = new AbortController();
    setSaved(null);
    setDraft(null);
    setFeedback(null);
    void fetch(`/api/protection?guild_id=${encodeURIComponent(guildId)}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error();
        const value = (await response.json()) as Protection;
        setSaved(value);
        setDraft(draftOf(value));
        setChannelMode(value.channel_ids.length ? "selected" : "all");
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setFeedback({
            kind: "error",
            text: "Could not load protection settings for this server.",
          });
      });
    return () => controller.abort();
  }, [guildId]);

  const guild = guilds.find((item) => item.id === guildId);
  useEffect(() => {
    onContextChange({
      server: guild?.name ?? null,
      enabled: saved?.enabled ?? null,
    });
  }, [guild?.name, guildId, saved, onContextChange]);
  const protectedChannels =
    guild?.channels.filter((item) => item.can_protect) ?? [];
  const detectionChannels =
    guild?.channels.filter((item) => item.can_notify) ?? [];
  const savedMode = saved?.channel_ids.length ? "selected" : "all";
  const dirty = Boolean(
    draft &&
    saved &&
    (channelMode !== savedMode ||
      JSON.stringify({
        ...draft,
        channel_ids: [...draft.channel_ids].sort(),
      }) !==
        JSON.stringify({
          ...draftOf(saved),
          channel_ids: [...saved.channel_ids].sort(),
        })),
  );
  const missingChannels = draft?.channel_ids.some(
    (id) => !protectedChannels.some((channel) => channel.id === id),
  );
  const missingDetectionChannel = Boolean(
    draft?.detection_channel_id &&
    !detectionChannels.some(
      (channel) => channel.id === draft.detection_channel_id,
    ),
  );

  function update(changes: Partial<ProtectionDraft>) {
    setDraft((current) => current && { ...current, ...changes });
    setFeedback(null);
  }

  async function saveChanges(event: React.FormEvent) {
    event.preventDefault();
    if (!backendAvailable || !draft || !guild || !dirty) return;
    if (channelMode === "selected" && !draft.channel_ids.length) {
      setFeedback({
        kind: "error",
        text: "Select at least one protected channel.",
      });
      return;
    }
    if (draft.notifications_enabled && !draft.detection_channel_id) {
      setFeedback({ kind: "error", text: "Select a Detection channel." });
      return;
    }
    setSaving(true);
    setFeedback(null);
    try {
      const response = await fetch("/api/protection", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-MediaGuard-Action": "save-protection",
        },
        body: JSON.stringify({
          guild_id: guild.id,
          ...draft,
          channel_ids: channelMode === "all" ? [] : draft.channel_ids,
        }),
      });
      if (!response.ok) {
        const error = (await response.json()) as { detail?: string };
        throw new Error(
          typeof error.detail === "string"
            ? error.detail
            : "Could not save protection settings.",
        );
      }
      const value = (await response.json()) as Protection;
      setSaved(value);
      setDraft(draftOf(value));
      setChannelMode(value.channel_ids.length ? "selected" : "all");
      setFeedback({ kind: "success", text: "Protection settings saved." });
    } catch (error) {
      setFeedback({
        kind: "error",
        text:
          error instanceof Error
            ? error.message
            : "Could not save protection settings.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="protection-column" aria-labelledby="protection-heading">
      <div className="column-heading">
        <h1 id="protection-heading">Protection</h1>
      </div>
      <div className="page-toolbar">
        <div className="guild-picker">
          <label id="guild-label">Server</label>
          <Select
            value={guildId || undefined}
            onValueChange={(value) => {
              setGuildId(value);
              setSaved(null);
              setDraft(null);
            }}
            disabled={!backendAvailable || !guilds.length}
          >
            <SelectTrigger
              aria-labelledby="guild-label"
              className="w-full min-w-0 sm:w-64"
            >
              <SelectValue placeholder="No connected server" />
            </SelectTrigger>
            <SelectContent>
              {guilds.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!backendAvailable}
          onClick={() => void refreshGuilds()}
        >
          Refresh channels
        </Button>
      </div>

      {!backendAvailable ? null : !guild ? (
        <div className="empty-state">
          Connect the MediaGuard bot to a server to configure protection. Saved
          settings remain in place while it is offline.
        </div>
      ) : !draft || !saved ? (
        <div className="empty-state">Loading protection settings…</div>
      ) : (
        <>
          <form onSubmit={(event) => void saveChanges(event)}>
            <div className="form-stack">
              <section className="form-section">
                <h2>Message protection</h2>
                <div className="setting-row">
                  <div>
                    <p>
                      Delete messages with confirmed audio or a blocked embed
                      phrase.
                    </p>
                  </div>
                  <Switch
                    aria-label="Protection enabled"
                    checked={draft.enabled}
                    disabled={!backendAvailable}
                    onCheckedChange={(enabled) => update({ enabled })}
                  />
                </div>
                <div className="setting-row channel-setting">
                  <div>
                    <strong>Protected channels</strong>
                    <p>
                      All relevant channels includes accessible guild text
                      channels.
                    </p>
                  </div>
                  <div
                    className="channel-mode"
                    role="radiogroup"
                    aria-label="Protected channels"
                  >
                    <label>
                      <input
                        type="radio"
                        name="channel-mode"
                        checked={channelMode === "all"}
                        disabled={!backendAvailable}
                        onChange={() => {
                          setChannelMode("all");
                          update({ channel_ids: [] });
                        }}
                      />
                      All relevant channels
                    </label>
                    <label>
                      <input
                        type="radio"
                        name="channel-mode"
                        checked={channelMode === "selected"}
                        disabled={!backendAvailable}
                        onChange={() => {
                          setChannelMode("selected");
                          setFeedback(null);
                        }}
                      />
                      Selected channels
                    </label>
                  </div>
                </div>
                {channelMode === "selected" && (
                  <div className="channel-options">
                    {protectedChannels.length ? (
                      protectedChannels.map((channel) => (
                        <label key={channel.id}>
                          <input
                            type="checkbox"
                            checked={draft.channel_ids.includes(channel.id)}
                            disabled={!backendAvailable}
                            onChange={(event) =>
                              update({
                                channel_ids: event.target.checked
                                  ? [...draft.channel_ids, channel.id]
                                  : draft.channel_ids.filter(
                                      (id) => id !== channel.id,
                                    ),
                              })
                            }
                          />
                          <span>#{channel.name}</span>
                        </label>
                      ))
                    ) : (
                      <p>
                        No accessible text channels are available for
                        protection.
                      </p>
                    )}
                    {missingChannels && (
                      <p className="field-error">
                        A saved channel is no longer available. Select
                        accessible channels before saving.
                      </p>
                    )}
                  </div>
                )}
              </section>

              <section className="form-section">
                <h2>Detection notifications</h2>
                <div className="setting-row">
                  <div>
                    <p>
                      One informational embed after a confirmed deletion.
                      Detected content is never reposted.
                    </p>
                  </div>
                  <Switch
                    aria-label="Detection notifications enabled"
                    checked={draft.notifications_enabled}
                    disabled={!backendAvailable}
                    onCheckedChange={(enabled) =>
                      update({
                        notifications_enabled: enabled,
                        detection_channel_id: enabled
                          ? draft.detection_channel_id
                          : null,
                      })
                    }
                  />
                </div>
                <div className="setting-row">
                  <div>
                    <strong>Detection channel</strong>
                    <p>Choose a channel where MediaGuard can send messages.</p>
                  </div>
                  <Select
                    value={draft.detection_channel_id ?? "none"}
                    onValueChange={(value) =>
                      update({
                        detection_channel_id: value === "none" ? null : value,
                      })
                    }
                    disabled={!backendAvailable || !draft.notifications_enabled}
                  >
                    <SelectTrigger
                      aria-label="Detection channel"
                      className="w-full min-w-0 sm:w-64"
                    >
                      <SelectValue placeholder="Select channel" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Select channel</SelectItem>
                      {detectionChannels.map((channel) => (
                        <SelectItem key={channel.id} value={channel.id}>
                          #{channel.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {missingDetectionChannel && (
                  <p className="field-error">
                    The saved Detection channel is no longer available.
                  </p>
                )}
              </section>

              <section className="form-section">
                <h2>Detected audio</h2>
                <div className="media-list">
                  {saved.media_types.map((type) => (
                    <Badge key={type} variant="outline">
                      {type}
                    </Badge>
                  ))}
                </div>
              </section>
            </div>
            <div className="save-bar">
              <span
                aria-live="polite"
                className={
                  feedback?.kind === "error" ? "save-error" : "save-feedback"
                }
              >
                {feedback?.text || (dirty ? "Unsaved changes" : "Saved")}
              </span>
              <Button
                type="submit"
                disabled={
                  !dirty ||
                  !backendAvailable ||
                  saving ||
                  !!missingChannels ||
                  !!missingDetectionChannel
                }
              >
                {saving ? "Saving…" : "Save changes"}
              </Button>
            </div>
          </form>
          <EmbedRules
            guildId={guildId}
            protectionEnabled={draft.enabled}
            backendAvailable={backendAvailable}
          />
        </>
      )}
    </section>
  );
}
