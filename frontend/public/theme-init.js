// پیش از اولین رسم و بدون وابستگی به React؛ سازگار با script-src 'self'.
(function () {
  var preference = 'system';
  try { var saved = localStorage.getItem('ats_theme'); if (saved === 'light' || saved === 'dark') preference = saved; } catch (_) {}
  var dark = false;
  try { dark = !!window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches; } catch (_) {}
  var effective = preference === 'system' ? (dark ? 'dark' : 'light') : preference;
  document.documentElement.classList.toggle('dark', effective === 'dark');
  document.documentElement.dataset.themePreference = preference;
  document.documentElement.style.colorScheme = effective;
  document.documentElement.style.backgroundColor = effective === 'dark' ? '#121822' : '#fcfcfa';
  document.documentElement.style.color = effective === 'dark' ? '#e2e8f0' : '#202936';
})();
