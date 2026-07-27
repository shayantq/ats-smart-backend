import { configureStore } from "@reduxjs/toolkit";
import authReducer from "./slices/authSlice";

export const store = configureStore({
  reducer: {
    auth: authReducer,
  },
});

// این دو تایپ برای استفاده‌ی type-safe از dispatch و selector در کل پروژه لازم‌اند
export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
