import { useQuery } from "@tanstack/react-query";
import { fetchMyApplications } from "../../services/candidatesApi";
import ApplicationTrackerCard from "./ApplicationTrackerCard";

export default function TrackerTab() {
  const {
    data: applications = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["candidate", "applications"],
    queryFn: fetchMyApplications,
  });

  if (isLoading) {
    return <p className="p-4 text-sm text-slate-600 dark:text-slate-300">در حال بارگذاری...</p>;
  }

  if (isError) {
    return (
      <p className="border-t border-red-200 dark:border-red-400 py-6 text-sm text-red-700 dark:text-red-300">
        خطا در دریافت وضعیت درخواست‌ها. اتصال به سرور را بررسی کن.
      </p>
    );
  }

  if (applications.length === 0) {
    return (
      <p className="border-y border-rule py-12 text-body text-muted">
        هنوز برای هیچ آگهی‌ای درخواست نداده‌ای.
      </p>
    );
  }

  return (
    <div className="grid min-w-0 grid-cols-1 gap-x-12 gap-y-6 lg:grid-cols-2">
      {applications.map((application) => (
        <ApplicationTrackerCard key={application.application_id} application={application} />
      ))}
    </div>
  );
}
