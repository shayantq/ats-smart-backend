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
    <div className="editorial-panel lg:col-span-2">
      <h3 className="mb-1 text-sm font-bold text-red-700 dark:text-red-300">حذف حساب</h3>
      <p className="reading-copy mb-4 text-sm text-muted">
        نام، شماره‌ی تماس، آدرس، ایمیل و فایل و متن رزومه‌ی شما برای همیشه پاک می‌شود و دیگر نمی‌توانید با این حساب وارد
        شوید. فقط آمار بی‌نام درخواست‌ها برای سازمان‌ها باقی می‌ماند.
      </p>
      {isConfirming ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
            className="rounded-md bg-red-600 dark:bg-red-700 px-4 py-2 text-sm font-semibold text-white dark:text-slate-100 hover:bg-red-700 dark:hover:bg-red-800 disabled:opacity-60"
          >
            {deleteMutation.isPending ? "در حال حذف..." : "بله، حسابم برای همیشه حذف شود"}
          </button>
          <button
            onClick={() => setIsConfirming(false)}
            disabled={deleteMutation.isPending}
            className="rounded-md border border-slate-500 dark:border-slate-500 bg-white dark:bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-900"
          >
            انصراف
          </button>
        </div>
      ) : (
        <button
          onClick={() => setIsConfirming(true)}
          className="rounded-md border border-red-300 dark:border-red-400 bg-white dark:bg-slate-800 px-4 py-2 text-sm font-semibold text-red-600 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950"
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
    return <p className="p-4 text-sm text-slate-600 dark:text-slate-300">در حال بارگذاری پروفایل...</p>;
  }

  if (isError) {
    return (
      <p className="border-t border-red-200 dark:border-red-400 py-6 text-sm text-red-700 dark:text-red-300">
        خطا در دریافت پروفایل. اتصال به سرور را بررسی کن.
      </p>
    );
  }

  return (
    <div className="grid min-w-0 grid-cols-1 items-start gap-x-12 gap-y-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <div className="editorial-panel">
        <h3 className="mb-5 text-heading text-ink">مشخصات فردی</h3>
        <p className="mb-6 break-all text-sm text-muted"><bdi>{profile?.email}</bdi></p>

        <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-caption font-medium text-muted">
            نام
            <input
              type="text"
              value={firstName}
              onChange={(event) => setFirstName(event.target.value)}
              className="candidate-field mt-2"
            />
          </label>
          <label className="text-caption font-medium text-muted">
            نام خانوادگی
            <input
              type="text"
              value={lastName}
              onChange={(event) => setLastName(event.target.value)}
              className="candidate-field mt-2"
            />
          </label>
        </div>

        <label className="mb-3 block text-caption font-medium text-muted">
          شماره تماس
          <input
            type="tel"
            dir="ltr"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            className="candidate-field mt-2"
          />
        </label>

        <div className="mb-6 text-caption font-medium text-muted">
          <p>مهارت‌ها</p>
          <div className="mt-1">
            <SkillTagInput skills={skills} onChange={setSkills} />
          </div>
        </div>

        <button
          onClick={handleSave}
          disabled={updateMutation.isPending}
          className="w-full rounded-md bg-slate-800 dark:bg-slate-700 px-4 py-2 text-sm font-semibold text-white dark:text-slate-100 transition-colors hover:bg-slate-900 dark:hover:bg-slate-950 disabled:cursor-not-allowed disabled:bg-slate-300 dark:disabled:bg-slate-700"
        >
          {updateMutation.isPending ? "در حال ذخیره..." : "ذخیره‌ی تغییرات"}
        </button>
      </div>

      <ResumeUploadWidget />

      <DeleteAccountSection />
    </div>
  );
}
