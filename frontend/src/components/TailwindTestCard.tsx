export default function TailwindTestCard() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900">
      <div className="max-w-sm rounded-xl bg-white dark:bg-slate-800 p-6 shadow-lg border border-slate-200 dark:border-slate-500">
        <h1 className="text-2xl font-bold text-blue-600 dark:text-blue-300 mb-2">
          تست Tailwind CSS
        </h1>
        <p className="text-slate-600 dark:text-slate-300 text-sm leading-relaxed">
          اگر این کارت با پس‌زمینه‌ی سفید، سایه، گوشه‌های گرد و متن آبی درست
          نمایش داده می‌شود، یعنی Tailwind CSS به‌درستی پیکربندی شده است.
        </p>
        <button className="mt-4 rounded-lg bg-blue-600 dark:bg-blue-700 px-4 py-2 text-white dark:text-slate-100 text-sm font-medium hover:bg-blue-700 dark:hover:bg-blue-800 transition-colors">
          دکمه‌ی تستی
        </button>
      </div>
    </div>
  );
}
