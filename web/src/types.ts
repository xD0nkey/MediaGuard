export type Status = {
  uptime_seconds: number;
  database: string;
  discord: {
    state: string;
    gateway: string;
    guild_count: number | null;
  };
  detections: {
    audio_blocked: number;
    recent_detection_at: string | null;
  };
  detection_retention_days: number;
};

export type ActivityEvent = {
  at: string;
  category: string;
  code: string;
};

export type Guild = {
  id: string;
  name: string;
  channels: {
    id: string;
    name: string;
    can_protect: boolean;
    can_notify: boolean;
  }[];
};

export type Protection = {
  enabled: boolean;
  action: "DELETE";
  channel_ids: string[];
  notifications_enabled: boolean;
  detection_channel_id: string | null;
  media_types: string[];
};

export type ProtectionDraft = Pick<
  Protection,
  "enabled" | "channel_ids" | "notifications_enabled" | "detection_channel_id"
>;

export type Detection = {
  at: string;
  guild_id: string;
  guild_name: string | null;
  channel_id: string;
  channel_name: string | null;
  message_id: string;
  author_id: string;
  author_name: string | null;
  media_type: string;
  source: "direct" | "forward";
  original_filename: string | null;
  deletion: string;
  deleted_at: string | null;
  notification: string;
};
