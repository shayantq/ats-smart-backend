import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { submitInterviewEvaluation } from "../../services/interviewsApi";
import { EVALUATION_CRITERIA } from "../../types/interview";
import type { Interview } from "../../types/interview";
import { useToast } from "../../context/ToastContext";
import { ApiError } from "../../services/apiClient";

interface EvaluationFormProps {
  interview: Interview;
  onSubmitted?: () => void;
}

function buildInitialScores(): Record<string, number> {
  return Object.fromEntries(EVALUATION_CRITERIA.map((criterion) => [criterion.key, 5]));
}

export default function EvaluationForm({ interview, onSubmitted }: EvaluationFormProps) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const [scores, setScores] = useState<Record<string, number>>(buildInitialScores);
  const [feedbackText, setFeedbackText] = useState("");

  // درخواست ناهمگام (React Query) — صفحه هیچ‌وقت قفل نمی‌شود؛ فقط دکمه‌ی
  // ثبت در حالت "در حال ثبت" می‌رود تا کاربر پاسخ سرور را ببیند.
  const submitMutation = useMutation({
    mutationFn: () =>
      submitInterviewEvaluation(interview.interview_id, {
        evaluation_scores: scores,
        feedback_text: feedbackText,
      }),
    onSuccess: () => {
      showToast("ارزیابی با موفقیت ثبت شد.", "success");
      // بدون رفرش صفحه، لیست مصاحبه‌ها را دوباره از سرور می‌خواند تا وضعیت
      // این ردیف فوراً به «تکمیل شده» تغییر کند
      void queryClient.invalidateQueries({ queryKey: ["interviews"] });
      onSubmitted?.();
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "ثبت ارزیابی با خطا مواجه شد.";
      showToast(message, "error");
    },
  });

  function handleScoreChange(key: string, value: number) {
    setScores((previous) => ({ ...previous, [key]: value }));
  }

  function handleSubmit() {
    if (feedbackText.trim().length === 0) {
      showToast("لطفاً بازخورد کیفی را هم بنویسید.", "error");
      return;
    }
    submitMutation.mutate();
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h4 className="mb-3 text-xs font-bold text-slate-700">فرم ارزیابی مصاحبه</h4>

      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {EVALUATION_CRITERIA.map((criterion) => (
          <label key={criterion.key} className="block text-xs font-medium text-slate-600">
            <div className="mb-1 flex items-center justify-between">
              <span>{criterion.label}</span>
              <span className="font-bold text-blue-700">{scores[criterion.key]}/۱۰</span>
            </div>
            <input
              type="range"
              min={1}
              max={10}
              value={scores[criterion.key]}
              onChange={(event) => handleScoreChange(criterion.key, Number(event.target.value))}
              className="w-full accent-blue-600"
            />
          </label>
        ))}
      </div>

      <label className="mb-4 block text-xs font-medium text-slate-600">
        بازخورد کیفی
        <textarea
          value={feedbackText}
          onChange={(event) => setFeedbackText(event.target.value)}
          rows={4}
          placeholder="نقاط قوت، نقاط ضعف، و جمع‌بندی نهایی خود از این مصاحبه را بنویسید..."
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </label>

      <button
        onClick={handleSubmit}
        disabled={submitMutation.isPending}
        className="w-full rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {submitMutation.isPending ? "در حال ثبت..." : "ثبت ارزیابی"}
      </button>
    </div>
  );
}
