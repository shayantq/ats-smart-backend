import { useRef, useState, type DragEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { fetchActiveJobs } from "../../services/jobsApi";
import { uploadResume } from "../../services/candidatesApi";
import { useToast } from "../../context/ToastContext";
import { ApiError } from "../../services/apiClient";

const ALLOWED_EXTENSIONS = [".pdf", ".docx"];

export default function ResumeUploadWidget() {
  const { showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);

  const { data: jobs = [] } = useQuery({ queryKey: ["jobs", "active"], queryFn: fetchActiveJobs });

  // درخواست ناهمگام (fetch) است، پس UI هیچ‌وقت قفل نمی‌شود؛ فقط دکمه‌ی ارسال
  // در حالت "در حال ارسال" می‌رود و بلافاصله بعد از پاسخ سرور، Toast موفقیت نشان داده می‌شود.
  const uploadMutation = useMutation({
    mutationFn: uploadResume,
    onSuccess: (result) => {
      showToast(result.message || "رزومه شما با موفقیت دریافت شد.", "success");
      setSelectedFile(null);
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "آپلود رزومه با خطا مواجه شد.";
      showToast(message, "error");
    },
  });

  function isAllowedFile(file: File): boolean {
    const lowerName = file.name.toLowerCase();
    return ALLOWED_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
  }

  function handleFileSelected(file: File | undefined) {
    if (!file) return;
    if (!isAllowedFile(file)) {
      showToast("فقط فایل PDF یا DOCX پذیرفته می‌شود.", "error");
      return;
    }
    setSelectedFile(file);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragOver(false);
    handleFileSelected(event.dataTransfer.files[0]);
  }

  function handleSubmit() {
    if (!selectedFile || !selectedJobId) return;
    uploadMutation.mutate({ jobId: selectedJobId, file: selectedFile });
  }

  return (
    <div className="editorial-panel">
      <h3 className="mb-5 text-heading text-ink">آپلود رزومه</h3>

      <label className="mb-3 block text-caption font-medium text-muted">
        آگهی شغلی مقصد
        <select
          value={selectedJobId}
          onChange={(event) => setSelectedJobId(event.target.value)}
          className="candidate-field mt-2"
        >
          <option value="">-- انتخاب کنید --</option>
          {jobs.map((job) => (
            <option key={job.job_id} value={job.job_id}>
              {job.title}
            </option>
          ))}
        </select>
      </label>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        className={`rounded-sm border border-dashed p-6 text-center text-sm transition-colors duration-200 ${
          isDragOver ? "border-slate-500 bg-wash" : "border-rule text-muted"
        }`}
      >
        {selectedFile ? (
          <p className="font-medium text-ink [overflow-wrap:anywhere]"><bdi>{selectedFile.name}</bdi></p>
        ) : (
          <p>فایل PDF یا DOCX را اینجا رها کن یا با دکمهٔ زیر انتخاب کن.</p>
        )}
        <button type="button" className="mt-3 border-b border-slate-400 px-2 py-1 text-ink hover:bg-wash" onClick={() => fileInputRef.current?.click()}>انتخاب فایل رزومه</button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx"
          aria-label="فایل رزومه"
          className="hidden"
          onChange={(event) => handleFileSelected(event.target.files?.[0])}
        />
      </div>

      <button
        onClick={handleSubmit}
        disabled={!selectedFile || !selectedJobId || uploadMutation.isPending}
        className="mt-3 w-full rounded-md bg-ink px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {uploadMutation.isPending ? "در حال ارسال..." : "ارسال رزومه"}
      </button>
    </div>
  );
}
