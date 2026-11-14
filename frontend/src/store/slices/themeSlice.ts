import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
export type ThemePreference = "light" | "dark" | "system";
export type EffectiveTheme = "light" | "dark";
export const validPreference = (value: unknown): ThemePreference => value === "light" || value === "dark" ? value : "system";
export const resolveTheme = (preference: ThemePreference, systemDark: boolean): EffectiveTheme => preference === "system" ? (systemDark ? "dark" : "light") : preference;
const themeSlice = createSlice({
  name: "theme",
  initialState: { preference: "system" as ThemePreference, systemDark: false },
  reducers: {
    setPreference(state, action: PayloadAction<ThemePreference>) { state.preference = action.payload; },
    setSystemDark(state, action: PayloadAction<boolean>) { state.systemDark = action.payload; },
  },
});
export const { setPreference, setSystemDark } = themeSlice.actions;
export default themeSlice.reducer;
