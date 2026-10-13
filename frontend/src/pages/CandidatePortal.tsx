import { useState } from "react";
import ProfileTab from "../components/candidate/ProfileTab";
import TrackerTab from "../components/candidate/TrackerTab";
import OffersTab from "../components/candidate/OffersTab";

type CandidateTab = "profile" | "tracker" | "offers";

const TABS: { value: CandidateTab; label: string }[] = [
  { value: "profile", label: "پروفایل" },
  { value: "tracker", label: "پیگیری وضعیت" },
  { value: "offers", label: "صندوق پیشنهادها" },
];

export default function CandidatePortal() {
  const [activeTab, setActiveTab] = useState<CandidateTab>("profile");

  return (
    <div className="min-h-screen bg-slate-100 p-4 sm:p-6">
      <div className="mx-auto max-w-5xl">
        <h1 className="mb-1 text-xl font-bold text-slate-800 sm:text-2xl">پورتال کارجو</h1>
        <p className="mb-6 text-sm text-slate-500">
          پروفایلت را کامل کن، وضعیت درخواست‌هایت را شفاف پیگیری کن و به پیشنهادهای شغلی پاسخ بده.
        </p>

        <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              role="tab"
              aria-selected={activeTab === tab.value}
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
