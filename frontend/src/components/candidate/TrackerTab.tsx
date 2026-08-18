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
    return <p className="p-4 text-sm text-slate-500">در حال بارگذاری...</p>;
  }

  if (isError) {
    return (
      <p className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-600">
        خطا در دریافت وضعیت درخواست‌ها. توکن دسترسی را بررسی کن.
      </p>
    );
  }

  if (applications.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        هنوز برای هیچ آگهی‌ای درخواست نداده‌ای.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {applications.map((application) => (
        <ApplicationTrackerCard key={application.application_id} application={application} />
      ))}
    </div>
  );
}
