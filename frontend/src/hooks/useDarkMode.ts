import { useAppDispatch, useAppSelector } from "../store/hooks";
import { resolveTheme, setPreference, type ThemePreference } from "../store/slices/themeSlice";
export function useDarkMode() {
  const dispatch = useAppDispatch();
  const state = useAppSelector(state => state.theme);
  return { preference: state.preference, effectiveTheme: resolveTheme(state.preference, state.systemDark), setTheme: (value: ThemePreference) => dispatch(setPreference(value)) };
}
