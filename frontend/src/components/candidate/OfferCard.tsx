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
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-bold text-slate-800">{offer.job_title}</h3>
      {offer.company_name && <p className="text-xs text-slate-500">{offer.company_name}</p>}
      <p className="mt-1 text-xs text-slate-400">
        تاریخ پیشنهاد: {new Date(offer.updated_at).toLocaleDateString("fa-IR")}
      </p>

      <div className="mt-4 flex gap-2">
        <button
          onClick={() => respondMutation.mutate("accept")}
          disabled={respondMutation.isPending}
          className="flex-1 rounded-md bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          قبول پیشنهاد
        </button>
        <button
          onClick={() => respondMutation.mutate("reject")}
          disabled={respondMutation.isPending}
          className="flex-1 rounded-md border border-red-300 px-3 py-2 text-xs font-semibold text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          رد پیشنهاد
        </button>
      </div>
    </div>
  );
}
