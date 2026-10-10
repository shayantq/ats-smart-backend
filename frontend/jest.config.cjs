/**
 * پیکربندی Jest — تست رندر کامپوننت‌های React (فایل‌های .test.tsx داخل src) در یک DOM شبیه‌سازی‌شده (jsdom).
 *
 * Babel فقط برای Jest استفاده می‌شود (babel.jest.config.cjs)، نه برای Vite — تا بیلد اصلی
 * پروژه دست‌نخورده بماند. import.meta.env (مخصوص Vite) با پلاگین transform-vite-meta-env
 * برای Jest قابل‌فهم می‌شود.
 *
 * اجرا:  npm test
 */
module.exports = {
  testEnvironment: "jsdom",
  roots: ["<rootDir>/src"],
  testMatch: ["**/*.test.ts?(x)"],
  setupFilesAfterEnv: ["<rootDir>/src/test/setupTests.ts"],
  transform: {
    "^.+\\.[jt]sx?$": ["babel-jest", { configFile: "./babel.jest.config.cjs" }],
  },
  moduleNameMapper: {
    "\\.(css)$": "<rootDir>/src/test/styleMock.cjs",
  },
  clearMocks: true,
};
