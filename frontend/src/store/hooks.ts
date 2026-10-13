import { useDispatch, useSelector, type TypedUseSelectorHook } from "react-redux";
import type { RootState, AppDispatch } from "./store";

// به‌جای useDispatch و useSelector خام، همیشه این دو هوک را در کامپوننت‌ها استفاده کنید
export const useAppDispatch: () => AppDispatch = useDispatch;
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;
