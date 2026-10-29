import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteMyAccount, fetchMyProfile, updateMyProfile } from "../../services/candidatesApi";
import SkillTagInput from "./SkillTagInput";
import ResumeUploadWidget from "./ResumeUploadWidget";
import { useToast } from "../../context/ToastContext";
import { ACCOUNT_DELETED_EVENT, ApiError } from "../../services/apiClient";

/**
 * حذف حساب (حق فراموش شدن): تأیید دومرحله‌ای، چون برگشت‌پذیر نیست. سرور هویت را ناشناس و فایل رزومه را حذف
 * می‌کند و همه‌ی نشست‌ها را می‌بندد؛ آمار بی‌نام درخواست‌ها برای سازمان‌ها می‌ماند.
 */
function DeleteAccountSection() {
  const { showToast } = useToast();
  const [isConfirming, setIsConfirming] = useState(false);
  const deleteMutation = useMutation({
    mutationFn: deleteMyAccount,
    onSuccess: () => window.dispatchEvent(new Event(ACCOUNT_DELETED_EVENT)),
    onError: () => showToast("حذف حساب ناموفق بود؛ دوباره تلاش کنید.", "error"),
  });

  return (
    <div className="rounded-xl border border-red-200 bg-red-50/40 p-4 lg:col-span-2">
      <h3 className="mb-1 text-sm font-bold text-red-700">حذف حساب</h3>
      <p className="mb-3 text-xs leading-6 text-slate-600">
        نام، شماره‌ی تماس، آدرس، ایمیل و فایل و متن رزومه‌ی شما برای همیشه پاک می‌شود و دیگر نمی‌توانید با این حساب وارد
        شوید. فقط آمار بی‌نام درخواست‌ها برای سازمان‌ها باقی می‌ماند.
      </p>
      {isConfirming ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-60"
          >
            {deleteMutation.isPending ? "در حال حذف..." : "بله، حسابم برای همیشه حذف شود"}
          </button>
          <button
            onClick={() => setIsConfirming(false)}
            disabled={deleteMutation.isPending}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50"
          >
            انصراف
          </button>
        </div>
      ) : (
        <button
          onClick={() => setIsConfirming(true)}
          className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-semibold text-red-600 hover:bg-red-50"
        >
          حذف حساب
        </button>
      )}
    </div>
  );
}

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
        خطا در دریافت پروفایل. اتصال به سرور را بررسی کن.
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

      <DeleteAccountSection />
    </div>
  );
}
