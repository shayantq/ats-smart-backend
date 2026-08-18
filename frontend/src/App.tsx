import { useState } from "react";
import { ToastProvider } from "./context/ToastContext";
import HRDashboard from "./pages/HRDashboard";
import CandidatePortal from "./pages/CandidatePortal";

type PortalView = "candidate" | "hr";

function App() {
  const [activeView, setActiveView] = useState<PortalView>("candidate");

  return (
    <ToastProvider>
      {/* سوییچر موقت بین دو پورتال — تا زمانی که صفحه‌ی ورود واقعی (Login) و
          مسیریابی بر اساس نقش کاربر ساخته شود */}
      <div className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl gap-1 px-4 pt-2 sm:px-6">
          <button
            onClick={() => setActiveView("candidate")}
            className={`rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
              activeView === "candidate"
                ? "bg-slate-100 text-slate-900"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            پورتال کارجو
          </button>
          <button
            onClick={() => setActiveView("hr")}
            className={`rounded-t-lg px-4 py-2 text-sm font-semibold transition-colors ${
              activeView === "hr" ? "bg-slate-100 text-slate-900" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            داشبورد HR
          </button>
        </div>
      </div>

      {activeView === "candidate" ? <CandidatePortal /> : <HRDashboard />}
    </ToastProvider>
  );
}

export default App;
