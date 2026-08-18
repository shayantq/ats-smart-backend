import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchMyProfile, updateMyProfile } from "../../services/candidatesApi";
import SkillTagInput from "./SkillTagInput";
import ResumeUploadWidget from "./ResumeUploadWidget";
import { useToast } from "../../context/ToastContext";
import { ApiError } from "../../services/apiClient";

const PROFILE_QUERY_KEY = ["candidate", "profile"];

export default function ProfileTab() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const { data: profile, isLoading, isError } = useQuery({
    queryKey: PROFILE_QUERY_KEY,
    queryFn: fetchMyProfile,
  });

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [skills, setSkills] = useState<string[]>([]);

  // فرم را با آخرین داده‌ی دریافتی از سرور پر می‌کند (فقط وقتی پروفایل واقعی می‌رسد)
  useEffect(() => {
    if (profile) {
      setFirstName(profile.first_name);
      setLastName(profile.last_name);
      setPhone(profile.phone ?? "");
      setSkills(profile.skills);
    }
  }, [profile]);

  const updateMutation = useMutation({
    mutationFn: updateMyProfile,
    onSuccess: (updated) => {
      queryClient.setQueryData(PROFILE_QUERY_KEY, updated);
      showToast("پروفایل با موفقیت به‌روزرسانی شد.", "success");
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "به‌روزرسانی پروفایل با خطا مواجه شد.";
      showToast(message, "error");
    },
  });

  function handleSave() {
    updateMutation.mutate({ first_name: firstName, last_name: lastName, phone, skills });
  }

  if (isLoading) {
    return <p className="p-4 text-sm text-slate-500">در حال بارگذاری پروفایل...</p>;
  }

  if (isError) {
    return (
      <p className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-600">
        خطا در دریافت پروفایل. توکن دسترسی را بررسی کن.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-sm font-bold text-slate-700">مشخصات فردی</h3>

        <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium text-slate-600">
            نام
            <input
              type="text"
              value={firstName}
              onChange={(event) => setFirstName(event.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </label>
          <label className="text-xs font-medium text-slate-600">
            نام خانوادگی
            <input
              type="text"
              value={lastName}
              onChange={(event) => setLastName(event.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </label>
        </div>

        <label className="mb-3 block text-xs font-medium text-slate-600">
          شماره تماس
          <input
            type="text"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </label>

        <label className="mb-4 block text-xs font-medium text-slate-600">
          مهارت‌ها
          <div className="mt-1">
            <SkillTagInput skills={skills} onChange={setSkills} />
          </div>
        </label>

        <button
          onClick={handleSave}
          disabled={updateMutation.isPending}
          className="w-full rounded-md bg-slate-800 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-900 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {updateMutation.isPending ? "در حال ذخیره..." : "ذخیره‌ی تغییرات"}
        </button>
      </div>

      <ResumeUploadWidget />
    </div>
  );
}
