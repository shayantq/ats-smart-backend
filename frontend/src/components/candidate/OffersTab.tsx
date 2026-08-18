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
    return <p className="p-4 text-sm text-slate-500">در حال بارگذاری...</p>;
  }

  if (isError) {
    return (
      <p className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-sm text-red-600">
        خطا در دریافت صندوق پیشنهادها. توکن دسترسی را بررسی کن.
      </p>
    );
  }

  if (offers.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        فعلاً هیچ پیشنهاد شغلی فعالی نداری.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {offers.map((offer) => (
        <OfferCard key={offer.application_id} offer={offer} />
      ))}
    </div>
  );
}
