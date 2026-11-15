// تطبیق‌دهنده‌های DOM برای expect (مثل toBeInTheDocument و toHaveAttribute)
import "@testing-library/jest-dom";

// jsdom هندسه ندارد؛ موتور واقعی Virtual با اندازه‌های قطعی تست می‌شود، نه فهرست جعلی.
jest.mock("@tanstack/react-virtual", () => {
  const actual = jest.requireActual("@tanstack/react-virtual");
  return { ...actual, useVirtualizer: (options: Record<string, unknown>) => actual.useVirtualizer({ ...options,
    observeElementRect: (_instance: unknown, callback: (rect: {width:number;height:number})=>void) => { callback({width:300,height:560}); return () => {}; },
    measureElement: () => 250,
    scrollToFn: () => {},
  }) };
});
