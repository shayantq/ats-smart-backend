/** یک نشست فعال (دستگاه) کاربر — منطبق با SessionResponse در app/schemas/auth.py */
export interface UserSession {
  id: string;
  browser: string;
  browser_version: string;
  os: string;
  os_version: string;
  device_type: "desktop" | "mobile" | "tablet" | "bot" | "other" | string;
  device: string;
  user_agent: string;
  ip: string;
  location: { country: string | null; country_code: string | null; city: string | null } | null;
  created_at: string;
  last_active_at: string;
  expires_at: string;
  is_current: boolean;
  suspicious: boolean;
}

export interface SessionListResponse {
  items: UserSession[];
}
