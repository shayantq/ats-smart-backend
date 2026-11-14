import type { Store } from "@reduxjs/toolkit";
import { resolveTheme, setPreference, setSystemDark, validPreference, type ThemePreference } from "./slices/themeSlice";
export const THEME_KEY = "ats_theme";
type ThemeStore = Pick<Store<{theme:{preference:ThemePreference;systemDark:boolean}}>, "getState" | "dispatch" | "subscribe">;

// فقط یک‌بار در ورودی برنامه نصب می‌شود؛ هوک‌ها شنوندهٔ جداگانه نمی‌سازند.
export function startThemeSync(store: ThemeStore) {
  let media: MediaQueryList | undefined;
  try { media = window.matchMedia?.("(prefers-color-scheme: dark)"); } catch { /* نبود API مانع اجرای برنامه نیست. */ }
  let preference: ThemePreference = validPreference(document.documentElement.dataset.themePreference);
  try { preference = validPreference(localStorage.getItem(THEME_KEY)); } catch { /* انتخاب بوت‌استرپ حفظ می‌شود. */ }
  store.dispatch(setSystemDark(media?.matches ?? false));
  store.dispatch(setPreference(preference));
  const apply = () => {
    const state = store.getState().theme;
    const effective = resolveTheme(state.preference, state.systemDark);
    document.documentElement.classList.toggle("dark", effective === "dark");
    document.documentElement.style.colorScheme = effective;
    document.documentElement.style.backgroundColor = effective === "dark" ? "#121822" : "#fcfcfa";
    document.documentElement.style.color = effective === "dark" ? "#e2e8f0" : "#202936";
    document.documentElement.dataset.themePreference = state.preference;
    if (preference !== state.preference) {
      preference = state.preference;
      try { localStorage.setItem(THEME_KEY, preference); } catch { /* انتخاب در همین صفحه همچنان کار می‌کند. */ }
    }
  };
  apply();
  const unsubscribe = store.subscribe(apply);
  const onSystem = (event: MediaQueryListEvent) => store.dispatch(setSystemDark(event.matches));
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_KEY || event.key === null) {
      preference = validPreference(event.newValue);
      store.dispatch(setPreference(preference));
    }
  };
  media?.addEventListener?.("change", onSystem);
  window.addEventListener("storage", onStorage);
  return () => { unsubscribe(); media?.removeEventListener?.("change", onSystem); window.removeEventListener("storage", onStorage); };
}
