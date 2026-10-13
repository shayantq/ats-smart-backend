/**
 * فراخوانی اندپوینت‌های احراز هویت بک‌اند:
 * - POST /api/v1/auth/login   ورود با ایمیل و رمز عبور → access_token
 * - GET  /api/v1/auth/me      اطلاعات و نقش کاربر لاگین‌شده
 */

import { apiRequest } from "./apiClient";
import type { AuthUser } from "../store/slices/authSlice";

interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

interface CurrentUserResponse {
  user_id: string;
  email: string;
  role: string;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    auth: false,
  });
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const me = await apiRequest<CurrentUserResponse>("/auth/me");
  return { id: me.user_id, email: me.email, role: me.role };
}
