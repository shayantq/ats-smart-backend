export default function TailwindTestCard() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100">
      <div className="max-w-sm rounded-xl bg-white p-6 shadow-lg border border-slate-200">
        <h1 className="text-2xl font-bold text-blue-600 mb-2">
          تست Tailwind CSS
        </h1>
        <p className="text-slate-600 text-sm leading-relaxed">
          اگر این کارت با پس‌زمینه‌ی سفید، سایه، گوشه‌های گرد و متن آبی درست
          نمایش داده می‌شود، یعنی Tailwind CSS به‌درستی پیکربندی شده است.
        </p>
        <button className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-white text-sm font-medium hover:bg-blue-700 transition-colors">
          دکمه‌ی تستی
        </button>
      </div>
    </div>
  );
}
