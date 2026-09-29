export type Status = {
  uptime_seconds: number;
  database: string;
  discord: {
    state: string;
    gateway: string;
    guild_count: number | null;
  };
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
  roles: {
    id: string;
    name: string;
  }[];
};

export type Protection = {
  enabled: boolean;
  action: "DELETE";
  channel_ids: string[];
  notifications_enabled: boolean;
  detection_channel_id: string | null;
  exempt_role_ids: string[];
  media_types: string[];
};

export type ProtectionDraft = Pick<
  Protection,
  | "enabled"
  | "channel_ids"
  | "notifications_enabled"
  | "detection_channel_id"
  | "exempt_role_ids"
>;

export type EmbedRule = {
  rule_id: string;
  guild_id: string;
  name: string;
  phrase: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};
