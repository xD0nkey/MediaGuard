import type { Detection } from "./types";

export function utcTime(value: string | null) {
  if (!value) return "—";
  return `${new Date(value).toLocaleString(undefined, {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })} UTC`;
}

export function mediaLabel(value: string) {
  return (
    {
      mp3: "MP3",
      wav: "WAV",
      flac: "FLAC",
      opus: "Ogg Opus",
      "ogg-vorbis": "Ogg Vorbis",
      m4a: "M4A",
    }[value] ?? value
  );
}

export function sourceLabel(value: Detection["source"]) {
  return {
    direct: "Direct attachment",
    forward: "Forwarded message",
    embed: "Discord embed",
    forwarded_embed: "Forwarded embed",
  }[value];
}

export function detectionLabel(value: Detection) {
  return value.detection_kind === "embed_phrase"
    ? "Blocked embed phrase"
    : `Audio: ${mediaLabel(value.media_type)}`;
}

export function outcome(detection: Detection) {
  if (detection.deletion === "succeeded") {
    return detection.notification.startsWith("failed")
      ? "Deleted · notification failed"
      : "Deleted";
  }
  if (detection.deletion === "failed_or_unknown")
    return "Deletion failed or unconfirmed";
  if (detection.deletion === "not_attempted") return "Not deleted";
  return "Deletion unconfirmed";
}
