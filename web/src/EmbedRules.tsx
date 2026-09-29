import { useEffect, useRef, useState } from "react";
import { Button } from "./components/ui/button";
import { Switch } from "./components/ui/switch";
import type { EmbedRule } from "./types";

type Draft = Pick<EmbedRule, "name" | "phrase" | "enabled"> & {
  rule_id?: string;
};

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Could not save the phrase.";
}

export default function EmbedRules({
  guildId,
  protectionEnabled,
  backendAvailable,
}: {
  guildId: string;
  protectionEnabled: boolean;
  backendAvailable: boolean;
}) {
  const [rules, setRules] = useState<EmbedRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const activeGuild = useRef(guildId);
  activeGuild.current = guildId;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setRules([]);
    setDraft(null);
    setDeleting(null);
    setFeedback("");
    void fetch(`/api/embed-rules?guild_id=${encodeURIComponent(guildId)}`, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not load blocked phrases.");
        const loaded = (await response.json()) as EmbedRule[];
        if (!controller.signal.aborted) {
          setRules(loaded);
          setLoading(false);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setFeedback(errorText(error));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [guildId]);

  async function persist(value: Draft) {
    const response = await fetch(
      value.rule_id ? `/api/embed-rules/${value.rule_id}` : "/api/embed-rules",
      {
        method: value.rule_id ? "PUT" : "POST",
        headers: {
          "Content-Type": "application/json",
          "X-MediaGuard-Action": "save-embed-rule",
        },
        body: JSON.stringify({
          guild_id: guildId,
          name: value.name.trim(),
          phrase: value.phrase.trim(),
          enabled: value.enabled,
        }),
      },
    );
    if (!response.ok) {
      const error = (await response.json()) as { detail?: string };
      throw new Error(error.detail || "Could not save the phrase.");
    }
    const saved = (await response.json()) as EmbedRule;
    if (activeGuild.current === guildId)
      setRules((current) =>
        value.rule_id
          ? current.map((item) =>
              item.rule_id === saved.rule_id ? saved : item,
            )
          : [...current, saved],
      );
    return saved;
  }

  async function save() {
    if (!backendAvailable || !draft || busy) return;
    if (!draft.name.trim() || !draft.phrase.trim()) {
      setFeedback("Enter a name and blocked phrase.");
      return;
    }
    setBusy(true);
    setFeedback("");
    try {
      await persist(draft);
      if (activeGuild.current === guildId) {
        setDraft(null);
        setFeedback("Blocked phrase saved.");
      }
    } catch (error) {
      if (activeGuild.current === guildId) setFeedback(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  async function toggle(item: EmbedRule, enabled: boolean) {
    if (!backendAvailable || busy) return;
    setBusy(true);
    setFeedback("");
    try {
      await persist({ ...item, enabled });
    } catch (error) {
      if (activeGuild.current === guildId) setFeedback(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  async function remove(ruleId: string) {
    if (!backendAvailable || busy) return;
    setBusy(true);
    setFeedback("");
    try {
      const response = await fetch(
        `/api/embed-rules/${ruleId}?guild_id=${encodeURIComponent(guildId)}`,
        {
          method: "DELETE",
          headers: { "X-MediaGuard-Action": "delete-embed-rule" },
        },
      );
      if (!response.ok) throw new Error("Could not delete the phrase.");
      if (activeGuild.current === guildId) {
        setRules((current) =>
          current.filter((item) => item.rule_id !== ruleId),
        );
        setDeleting(null);
        setFeedback("Blocked phrase deleted.");
      }
    } catch (error) {
      if (activeGuild.current === guildId) setFeedback(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="form-section embed-rules-section">
      <div className="section-heading-line">
        <h2>Blocked embed phrases</h2>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={
            !backendAvailable ||
            busy ||
            loading ||
            rules.length >= 50 ||
            draft !== null
          }
          onClick={() => {
            setDraft({ name: "", phrase: "", enabled: true });
            setFeedback("");
          }}
        >
          Add phrase
        </Button>
      </div>
      <p className="rules-intro">
        Phrases matched in Discord embed text.
        {!protectionEnabled && " Protection is currently off."}
      </p>
      {loading ? (
        <p className="rules-state">Loading blocked phrases…</p>
      ) : !rules.length && !draft ? (
        <p className="rules-state">No blocked phrases configured.</p>
      ) : (
        <div className="rules-list">
          {rules.map((item) => (
            <div className="rule-row" key={item.rule_id}>
              <div className="rule-copy">
                <strong>{item.name}</strong>
                <span>“{item.phrase}”</span>
              </div>
              {deleting === item.rule_id ? (
                <div className="rule-actions">
                  <span>Delete this phrase?</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleting(null)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={!backendAvailable || busy}
                    onClick={() => void remove(item.rule_id)}
                  >
                    Delete
                  </Button>
                </div>
              ) : (
                <div className="rule-actions">
                  <Switch
                    aria-label={`${item.enabled ? "Disable" : "Enable"} ${item.name}`}
                    checked={item.enabled}
                    disabled={!backendAvailable || busy}
                    onCheckedChange={(enabled) => void toggle(item, enabled)}
                  />
                  <span>{item.enabled ? "Enabled" : "Disabled"}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={!backendAvailable || busy || draft !== null}
                    onClick={() => {
                      setDraft(item);
                      setFeedback("");
                    }}
                  >
                    Edit
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={!backendAvailable || busy || draft !== null}
                    onClick={() => setDeleting(item.rule_id)}
                  >
                    Delete
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {draft && (
        <div className="rule-editor">
          <div className="rule-fields">
            <label>
              Name
              <input
                value={draft.name}
                disabled={!backendAvailable}
                maxLength={80}
                onChange={(event) =>
                  setDraft({ ...draft, name: event.target.value })
                }
                placeholder="Rule name"
              />
            </label>
            <label>
              Blocked phrase
              <input
                value={draft.phrase}
                disabled={!backendAvailable}
                maxLength={160}
                onChange={(event) =>
                  setDraft({ ...draft, phrase: event.target.value })
                }
                placeholder="Phrase to block"
              />
            </label>
          </div>
          <div className="rule-editor-actions">
            <Button
              type="button"
              size="sm"
              disabled={!backendAvailable || busy}
              onClick={() => void save()}
            >
              {busy ? "Saving…" : "Save phrase"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setDraft(null)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
      {feedback && (
        <p className="rules-feedback" role="status">
          {feedback}
        </p>
      )}
    </section>
  );
}
