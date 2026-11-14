import { configureStore } from "@reduxjs/toolkit";
import theme, { resolveTheme, setPreference, validPreference } from "./slices/themeSlice";
import { startThemeSync, THEME_KEY } from "./themeSync";

let changed: ((e: {matches:boolean}) => void) | undefined;
const remove = jest.fn();
beforeEach(() => {
  localStorage.clear(); document.documentElement.className = ""; delete document.documentElement.dataset.themePreference;
  changed = undefined; remove.mockClear();
  Object.defineProperty(window, "matchMedia", {configurable:true,writable:true,value:jest.fn(() => ({matches:true,addEventListener: (_:string,fn:typeof changed) => {changed=fn;},removeEventListener:remove}))});
});
test("انتخاب سیستم و ورودی نامعتبر به شکل قطعی حل می‌شوند", () => {
  expect(validPreference("invalid")).toBe("system");
  expect(resolveTheme("system",true)).toBe("dark");
  expect(resolveTheme("system",false)).toBe("light");
  expect(resolveTheme("light",true)).toBe("light");
});
test("انتخاب دستی ذخیره و بر تنظیم سیستم مقدم می‌شود؛ سپس سیستم دوباره دنبال می‌شود", () => {
  const store=configureStore({reducer:{theme}}); const stop=startThemeSync(store);
  expect(document.documentElement).toHaveClass("dark");
  store.dispatch(setPreference("light"));
  expect(localStorage.getItem(THEME_KEY)).toBe("light");
  changed?.({matches:true});expect(document.documentElement).not.toHaveClass("dark");
  store.dispatch(setPreference("system"));expect(document.documentElement).toHaveClass("dark");
  changed?.({matches:false});expect(document.documentElement).not.toHaveClass("dark");
  stop();expect(remove).toHaveBeenCalledTimes(1);
});
test("انتخاب ذخیره‌شده و تغییر یا پاک شدن آن از تب دیگر اعمال می‌شود", () => {
  localStorage.setItem(THEME_KEY,"light");const store=configureStore({reducer:{theme}});const stop=startThemeSync(store);
  expect(document.documentElement.style.colorScheme).toBe("light");
  window.dispatchEvent(new StorageEvent("storage",{key:THEME_KEY,newValue:"dark"}));
  expect(store.getState().theme.preference).toBe("dark");expect(document.documentElement).toHaveClass("dark");
  window.dispatchEvent(new StorageEvent("storage",{key:THEME_KEY,newValue:null}));expect(store.getState().theme.preference).toBe("system");
  stop();window.dispatchEvent(new StorageEvent("storage",{key:THEME_KEY,newValue:"light"}));expect(store.getState().theme.preference).toBe("system");
});
test("خطای ذخیره‌سازی و نبود matchMedia برنامه را متوقف نمی‌کند", () => {
  const read=jest.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw Error("blocked");});
  const write=jest.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw Error("blocked");});
  Object.defineProperty(window,"matchMedia",{value:undefined,configurable:true});
  const store=configureStore({reducer:{theme}});const stop=startThemeSync(store);
  expect(()=>store.dispatch(setPreference("dark"))).not.toThrow();expect(document.documentElement).toHaveClass("dark");stop();read.mockRestore();write.mockRestore();
});
