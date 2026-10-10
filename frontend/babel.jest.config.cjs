// پیکربندی Babel فقط برای Jest (بنگرید jest.config.cjs) — Vite از این فایل استفاده نمی‌کند.
module.exports = {
  presets: [
    ["@babel/preset-env", { targets: { node: "current" } }],
    ["@babel/preset-react", { runtime: "automatic" }],
    "@babel/preset-typescript",
  ],
  plugins: ["babel-plugin-transform-vite-meta-env"],
};
