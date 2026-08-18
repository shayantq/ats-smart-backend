import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import ProfileTab from "../components/candidate/ProfileTab";
import TrackerTab from "../components/candidate/TrackerTab";
import OffersTab from "../components/candidate/OffersTab";
import { getToken, setToken as saveToken } from "../services/tokenStorage";

type CandidateTab = "profile" | "tracker" | "offers";

const TABS: { value: CandidateTab; label: string }[] = [
  { value: "profile", label: "پروفایل" },
  { value: "tracker", label: "پیگیری وضعیت" },
  { value: "offers", label: "صندوق پیشنهادها" },
];

export default function CandidatePortal() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<CandidateTab>("profile");
  const [tokenInput, setTokenInput] = useState(getToken() ?? "");

  function handleSaveToken() {
    saveToken(tokenInput.trim());
    // بعد از تغییر توکن، پروفایل/رهگیر/صندوق پیشنهادها باید با هویت جدید دوباره خوانده شوند
    void queryClient.invalidateQueries({ queryKey: ["candidate"] });
  }

  return (
    <div className="min-h-screen bg-slate-100 p-4 sm:p-6">
      <div className="mx-auto max-w-5xl">
        <h1 className="mb-1 text-xl font-bold text-slate-800 sm:text-2xl">پورتال کارجو</h1>
        <p className="mb-6 text-sm text-slate-500">
          پروفایلت را کامل کن، وضعیت درخواست‌هایت را شفاف پیگیری کن و به پیشنهادهای شغلی پاسخ بده.
        </p>

        {/* بخش موقت توسعه: تا زمانی که صفحه‌ی ورود (Login) واقعی ساخته شود */}
        <div className="mb-6 flex flex-col gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 sm:flex-row sm:items-center">
          <label className="shrink-0 text-xs font-semibold text-amber-800">توکن دسترسی (Candidate):</label>
          <input
            type="text"
            value={tokenInput}
            onChange={(event) => setTokenInput(event.target.value)}
            placeholder="access_token را از Swagger کپی و اینجا وارد کنید"
            className="flex-1 rounded-md border border-amber-300 px-3 py-1.5 text-xs"
          />
          <button
            onClick={handleSaveToken}
            className="shrink-0 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700"
          >
            ذخیره توکن
          </button>
        </div>

        <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={`shrink-0 rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
                activeTab === tab.value
                  ? "border-b-2 border-blue-600 text-blue-700"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "profile" && <ProfileTab />}
        {activeTab === "tracker" && <TrackerTab />}
        {activeTab === "offers" && <OffersTab />}
      </div>
    </div>
  );
}
