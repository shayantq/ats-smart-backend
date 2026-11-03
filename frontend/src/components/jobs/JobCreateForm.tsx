import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import SkillTagInput from "../candidate/SkillTagInput";
import { useToast } from "../../context/ToastContext";
import { ApiError } from "../../services/apiClient";
import { createJob } from "../../services/jobsApi";
import type { Job, JobCreatePayload } from "../../types/job";

// همان مقادیری که موتور نمره‌دهی می‌شناسد (app/core/matching_engine.py)
const SENIORITY_OPTIONS = [
  { value: "", label: "مهم نیست" },
  { value: "junior", label: "تازه‌کار (۰ تا ۲ سال)" },
  { value: "mid-level", label: "میانی (۲ تا ۵ سال)" },
  { value: "senior", label: "ارشد (۵ تا ۱۰ سال)" },
  { value: "lead", label: "سرپرست (۸ سال به بالا)" },
  { value: "principal", label: "اصلی (۱۰ سال به بالا)" },
];
const EDUCATION_OPTIONS = [
  { value: "", label: "مهم نیست" },
  { value: "دیپلم", label: "دیپلم" },
  { value: "کاردانی", label: "کاردانی" },
  { value: "کارشناسی", label: "کارشناسی" },
  { value: "کارشناسی ارشد", label: "کارشناسی ارشد" },
  { value: "دکتری", label: "دکتری" },
];

const inputClass = "mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none";
const labelClass = "block text-xs font-semibold text-slate-600";

/**
 * ثبت آگهی شغلی تازه برای سازمان کاربر (POST /api/v1/jobs/ — Admin/HR_Manager). مهارت‌ها، سطح ارشدیت، تحصیلات و
 * موقعیت در نمره‌ی تطابق رزومه‌ها (Matching Score) به کار می‌روند.
 */
export default function JobCreateForm({ onCreated }: { onCreated: (job: Job) => void }) {
  const { showToast } = useToast();
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState("");
  const [description, setDescription] = useState("");
  const [skills, setSkills] = useState<string[]>([]);
  const [salaryRange, setSalaryRange] = useState("");
  const [seniority, setSeniority] = useState("");
  const [education, setEducation] = useState("");
  const [location, setLocation] = useState("");

  const mutation = useMutation({
    mutationFn: createJob,
    onSuccess: (job) => {
      showToast(`آگهی «${job.title}» منتشر شد.`);
      onCreated(job);
    },
    onError: (error) => {
      const message =
        error instanceof ApiError && error.status === 403
          ? "فقط مدیر سازمان یا کارشناس منابع انسانی می‌تواند آگهی ثبت کند."
          : error instanceof ApiError && error.status === 422
            ? "عنوان آگهی دست‌کم ۲ کاراکتر باشد و فیلدها از حد مجاز طولانی‌تر نباشند."
            : "ثبت آگهی ناموفق بود؛ دوباره تلاش کنید.";
      showToast(message, "error");
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const optional = (value: string) => value.trim() || undefined;
    const payload: JobCreatePayload = {
      title: title.trim(),
      department: optional(department),
      description: optional(description),
      skills_required: skills,
      salary_range: optional(salaryRange),
      required_seniority: optional(seniority),
      required_education: optional(education),
      location: optional(location),
    };
    mutation.mutate(payload);
  }

  return (
    <form onSubmit={handleSubmit} aria-labelledby="job-create-title" className="rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
      <h2 id="job-create-title" className="mb-1 text-sm font-bold text-slate-700">
        ثبت آگهی شغلی تازه
      </h2>
      <p className="mb-4 text-xs text-slate-500">
        آگهی بلافاصله فعال می‌شود. مهارت‌ها، سطح ارشدیت، تحصیلات و موقعیت در نمره‌ی تطابق رزومه‌ها به کار می‌روند.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className={`${labelClass} sm:col-span-2`}>
          عنوان آگهی *
          <input required minLength={2} maxLength={255} value={title} onChange={(e) => setTitle(e.target.value)} className={inputClass} />
        </label>
        <label className={labelClass}>
          واحد سازمانی
          <input maxLength={100} value={department} onChange={(e) => setDepartment(e.target.value)} className={inputClass} />
        </label>
        <label className={labelClass}>
          موقعیت مکانی
          <input maxLength={100} value={location} onChange={(e) => setLocation(e.target.value)} className={inputClass} />
        </label>
        <label className={labelClass}>
          سطح ارشدیت
          <select value={seniority} onChange={(e) => setSeniority(e.target.value)} className={inputClass}>
            {SENIORITY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          حداقل تحصیلات
          <select value={education} onChange={(e) => setEducation(e.target.value)} className={inputClass}>
            {EDUCATION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className={labelClass}>
          بازه‌ی حقوق
          <input maxLength={50} value={salaryRange} onChange={(e) => setSalaryRange(e.target.value)} className={inputClass} />
        </label>
        <div className={`${labelClass} sm:col-span-2`}>
          مهارت‌های لازم
          <div className="mt-1">
            <SkillTagInput skills={skills} onChange={setSkills} />
          </div>
        </div>
        <label className={`${labelClass} sm:col-span-2`}>
          شرح آگهی
          <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} className={inputClass} />
        </label>
      </div>

      <button
        type="submit"
        disabled={mutation.isPending || title.trim().length < 2}
        className="mt-4 w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
      >
        {mutation.isPending ? "در حال ثبت..." : "انتشار آگهی"}
      </button>
    </form>
  );
}
