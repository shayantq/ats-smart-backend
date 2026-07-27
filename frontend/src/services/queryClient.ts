import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000, // یک دقیقه: داده‌ی کش‌شده تا این مدت "تازه" در نظر گرفته می‌شود
      retry: 1,
    },
  },
});
