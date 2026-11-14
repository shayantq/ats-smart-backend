import { useMutation, useQueryClient } from "@tanstack/react-query";
import { respondToOffer } from "../../services/candidatesApi";
import { useToast } from "../../context/ToastContext";
import { ApiError } from "../../services/apiClient";
import type { OfferDecision, OfferInboxItem } from "../../types/candidate";

interface OfferCardProps {
  offer: OfferInboxItem;
}

export default function OfferCard({ offer }: OfferCardProps) {
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
      <h3 className="min-w-0 text-heading text-ink [overflow-wrap:anywhere]">{offer.job_title}</h3>
      {offer.company_name && <p className="mt-2 text-body text-muted [overflow-wrap:anywhere]">{offer.company_name}</p>}
      <p className="mt-1 text-caption text-muted">
        تاریخ پیشنهاد: {new Date(offer.updated_at).toLocaleDateString("fa-IR")}
      </p>

      <div className="mt-6 flex flex-wrap gap-3">
        <button
          onClick={() => respondMutation.mutate("accept")}
          disabled={respondMutation.isPending}
          className="rounded-sm bg-ink px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          قبول پیشنهاد
        </button>
        <button
          onClick={() => respondMutation.mutate("reject")}
          disabled={respondMutation.isPending}
          className="rounded-sm border border-red-200 px-5 py-2.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          رد پیشنهاد
        </button>
      </div>
    </div>
  );
}
