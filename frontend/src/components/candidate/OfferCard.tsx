import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId } from "react";
import { respondToOffer } from "../../services/candidatesApi";
import { useToast } from "../../context/ToastContext";
import { ApiError } from "../../services/apiClient";
import type { OfferDecision, OfferInboxItem } from "../../types/candidate";

interface OfferCardProps {
  offer: OfferInboxItem;
}

export default function OfferCard({ offer }: OfferCardProps) {
  const title = useId();
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const respondMutation = useMutation({
    mutationFn: (decision: OfferDecision) => respondToOffer(offer.application_id, decision),
    onSuccess: (result) => {
      showToast(result.message, "success");
      void queryClient.invalidateQueries({ queryKey: ["candidate", "offers"] });
      void queryClient.invalidateQueries({ queryKey: ["candidate", "applications"] });
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "ثبت پاسخ با خطا مواجه شد.";
      showToast(message, "error");
    },
  });

  return (
    <div className="editorial-panel">
      <h3 id={title} className="min-w-0 text-heading text-ink [overflow-wrap:anywhere]">{offer.job_title}</h3>
      {offer.company_name && <p className="mt-2 text-body text-muted [overflow-wrap:anywhere]">{offer.company_name}</p>}
      <p className="mt-1 text-caption text-muted">
        تاریخ پیشنهاد: {new Date(offer.updated_at).toLocaleDateString("fa-IR")}
      </p>

      <div className="mt-6 flex flex-wrap gap-3">
        <button
          onClick={() => respondMutation.mutate("accept")}
          aria-describedby={title}
          disabled={respondMutation.isPending}
          className="rounded-sm bg-ink dark:bg-slate-700 px-5 py-2.5 text-sm font-medium text-white dark:text-slate-100 hover:bg-slate-700 dark:hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300 dark:disabled:bg-slate-700"
        >
          قبول پیشنهاد
        </button>
        <button
          onClick={() => respondMutation.mutate("reject")}
          aria-describedby={title}
          disabled={respondMutation.isPending}
          className="rounded-sm border border-red-200 dark:border-red-400 px-5 py-2.5 text-sm font-medium text-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950 disabled:cursor-not-allowed disabled:opacity-50"
        >
          رد پیشنهاد
        </button>
      </div>
    </div>
  );
}
