import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { configureStore } from "@reduxjs/toolkit";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import authReducer from "../store/slices/authSlice";
import { ToastProvider } from "../context/ToastContext";

/**
 * رندر یک کامپوننت با همان Providerهای برنامه‌ی واقعی (Redux + React Query + Toast)، ولی با
 * نمونه‌های تازه برای هر تست تا هیچ وضعیتی بین تست‌ها نشت نکند.
 */
export function renderWithProviders(ui: ReactElement) {
  const store = configureStore({ reducer: { auth: authReducer } });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

  const result = render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>{ui}</ToastProvider>
      </QueryClientProvider>
    </Provider>,
  );
  return { ...result, store, queryClient };
}

/** یک پاسخ ساختگی fetch (برای jest.spyOn(global, "fetch")) */
export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

/**
 * fetch ساختگی بر اساس مسیر: کلید = بخشی از URL (مثلاً "/auth/me")، مقدار = پاسخ.
 * محیط jsdom اصلاً fetch ندارد؛ این تابع آن را روی globalThis قرار می‌دهد.
 */
export function mockFetchRoutes(routes: Record<string, () => Response>): jest.Mock {
  const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const match = Object.keys(routes).find((route) => url.includes(route));
    if (!match) {
      throw new Error(`fetch ساختگی برای این آدرس تعریف نشده: ${url}`);
    }
    return routes[match]();
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}
