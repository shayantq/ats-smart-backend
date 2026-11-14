import { useDarkMode } from "../hooks/useDarkMode";
import { validPreference } from "../store/slices/themeSlice";
export default function ThemeControl() {
  const { preference, setTheme } = useDarkMode();
  return <label className="flex items-center gap-2 text-caption text-muted">نمایش
    <select aria-label="حالت نمایش" value={preference} onChange={event => setTheme(validPreference(event.target.value))} className="rounded-sm border border-slate-500 bg-paper px-2 py-1 text-ink transition-colors duration-200 dark:bg-slate-800">
      <option value="light">روشن</option><option value="dark">تاریک</option><option value="system">تنظیم سیستم</option>
    </select>
  </label>;
}
