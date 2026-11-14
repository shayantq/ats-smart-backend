import { useQuery } from "@tanstack/react-query";
import { fetchMyOffers } from "../../services/candidatesApi";
import OfferCard from "./OfferCard";

export default function OffersTab() {
  const {
    data: offers = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["candidate", "offers"],
    queryFn: fetchMyOffers,
  });

  if (isLoading) {
    return <p className="p-4 text-sm text-slate-600 dark:text-slate-300">در حال بارگذاری...</p>;
  }

  if (isError) {
    return (
      <p className="border-t border-red-200 dark:border-red-400 py-6 text-sm text-red-700 dark:text-red-300">
        خطا در دریافت صندوق پیشنهادها. اتصال به سرور را بررسی کن.
      </p>
    );
  }

  if (offers.length === 0) {
    return (
      <p className="border-y border-rule py-12 text-body text-muted">
        فعلاً هیچ پیشنهاد شغلی فعالی نداری.
      </p>
    );
  }

  return (
    <div className="grid min-w-0 grid-cols-1 gap-x-12 gap-y-6 lg:grid-cols-2">
      {offers.map((offer) => (
        <OfferCard key={offer.application_id} offer={offer} />
      ))}
    </div>
  );
}
