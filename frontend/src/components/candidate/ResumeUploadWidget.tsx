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
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-bold text-slate-700">آپلود رزومه</h3>

      <label className="mb-3 block text-xs font-medium text-slate-600">
        آگهی شغلی مقصد
        <select
          value={selectedJobId}
          onChange={(event) => setSelectedJobId(event.target.value)}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
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
        onClick={() => fileInputRef.current?.click()}
        className={`cursor-pointer rounded-lg border-2 border-dashed p-6 text-center text-sm transition-colors ${
          isDragOver ? "border-blue-400 bg-blue-50" : "border-slate-300 text-slate-500"
        }`}
      >
        {selectedFile ? (
          <p className="font-medium text-slate-700">{selectedFile.name}</p>
        ) : (
          <p>فایل PDF یا DOCX را اینجا رها کن، یا کلیک کن تا انتخاب کنی</p>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          onChange={(event) => handleFileSelected(event.target.files?.[0])}
        />
      </div>

      <button
        onClick={handleSubmit}
        disabled={!selectedFile || !selectedJobId || uploadMutation.isPending}
        className="mt-3 w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {uploadMutation.isPending ? "در حال ارسال..." : "ارسال رزومه"}
      </button>
    </div>
  );
}
