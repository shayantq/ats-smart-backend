import { useRef, useState, type KeyboardEvent } from "react";
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
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function navigateTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowLeft") next = (index + 1) % TABS.length;
    else if (event.key === "ArrowRight") next = (index + TABS.length - 1) % TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TABS.length - 1;
    else return;
    event.preventDefault();
    setActiveTab(TABS[next].value);
    tabRefs.current[next]?.focus();
  }

  return (
    <div className="editorial-shell">
      <div className="min-w-0">
        <p className="editorial-label mb-2">مسیر شغلی شما</p>
        <h1 className="mb-2 text-display text-ink">پورتال کارجو</h1>
        <p className="reading-copy mb-8 text-muted">
          پروفایلت را کامل کن، وضعیت درخواست‌هایت را شفاف پیگیری کن و به پیشنهادهای شغلی پاسخ بده.
        </p>

        <div role="tablist" aria-label="بخش‌های پورتال کارجو" className="mb-8 flex flex-wrap gap-x-5 border-b border-rule">
          {TABS.map((tab, index) => (
            <button
              key={tab.value}
              role="tab"
              id={`candidate-tab-${tab.value}`}
              aria-controls={`candidate-panel-${tab.value}`}
              aria-selected={activeTab === tab.value}
              tabIndex={activeTab === tab.value ? 0 : -1}
              ref={(element) => { tabRefs.current[index] = element; }}
              onKeyDown={(event) => navigateTabs(event, index)}
              onClick={() => setActiveTab(tab.value)}
              className={`border-b-2 py-3 text-sm font-medium transition-colors duration-200 ${
                activeTab === tab.value
                  ? "border-ink text-ink"
                  : "border-transparent text-muted hover:border-slate-300 hover:text-ink"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <section role="tabpanel" id={`candidate-panel-${activeTab}`} aria-labelledby={`candidate-tab-${activeTab}`} tabIndex={0} className="min-w-0">
        {activeTab === "profile" && <ProfileTab />}
        {activeTab === "tracker" && <TrackerTab />}
        {activeTab === "offers" && <OffersTab />}
        </section>
      </div>
    </div>
  );
}
