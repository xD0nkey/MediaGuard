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
  return value === "forward" ? "Forwarded message" : "Direct attachment";
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
