# ATS Smart — Frontend

رابط کاربری پلتفرم هوشمند جذب و استخدام، مبتنی بر React + TypeScript + Vite + Tailwind CSS.

این پوشه (`frontend/`) بخش فرانت‌اند پروژه است و کنار پوشه‌ی بک‌اند (`app/`) در همین ریپو قرار دارد.

## راه‌اندازی محیط توسعه

از ریشه ریپو، وارد این پوشه شوید:

```bash
cd frontend
npm install
```

## اجرای پروژه در حالت توسعه

```bash
npm run dev
```

سرور توسعه معمولا روی آدرس زیر بالا میاد:
http://localhost:5173

⚠️ برای اینکه بورد کانبان بتواند با بک‌اند صحبت کند، بک‌اند هم باید هم‌زمان روی
`http://localhost:8000` در حال اجرا باشد (`uvicorn app.main:app --reload`).

## بورد کانبان داشبورد HR

صفحه‌ی اصلی اپلیکیشن (`src/pages/HRDashboard.tsx`) بورد کانبان مدیریت متقاضیان یک آگهی
شغلی خاص را نشان می‌دهد — کارت هر کارجو با کشیدن (Drag & Drop) بین ستون‌ها جابه‌جا می‌شود.

چون هنوز صفحه‌ی لاگین و صفحه‌ی انتخاب آگهی در فرانت‌اند ساخته نشده، فعلاً دو فیلد بالای
صفحه («شناسه‌ی آگهی» و «توکن دسترسی») باید دستی پر شوند تا بورد بتواند با بک‌اند صحبت کند.

## مدیریت وضعیت (State Management)

- **Redux Toolkit**: برای وضعیت های سراسری اپلیکیشن (فعلاً فقط اطلاعات کاربر لاگین شده در `store/slices/authSlice.ts`). به‌جای `useDispatch`/`useSelector` خام، همیشه از هوک های تایپ‌شده در `store/hooks.ts` استفاده کنید.
- **React Query**: برای گرفتن و کش کردن داده از بک اند (تنظیماتش در `services/queryClient.ts`).

هر دو Provider در `main.tsx` دور کامپوننت اصلی (`App`) پیچیده شده اند.

برای دیدن وضعیت Store در مرورگر، اکستنشن Redux DevTools را نصب کنید.

## ساختار پروژه

```
frontend/
├── src/
│   ├── components/
│   │   ├── ApplicationCard.tsx     # کارت کارجو (Draggable) + نشان امتیاز هوش مصنوعی
│   │   ├── KanbanColumn.tsx         # یک ستون بورد (Droppable)
│   │   └── KanbanBoard.tsx           # هماهنگ‌کننده‌ی بورد: fetch, drag&drop, snap-back, toast
│   ├── context/
│   │   └── ToastContext.tsx           # سیستم Toast Notification (موفقیت/خطا)
│   ├── pages/
│   │   └── HRDashboard.tsx             # صفحه‌ی داشبورد HR (فرم Job ID/Token موقت + بورد)
│   ├── services/
│   │   ├── apiClient.ts                # fetch wrapper با هدر Authorization و خطای تایپ‌شده
│   │   ├── applicationsApi.ts           # GET لیست و PUT تغییر وضعیت
│   │   ├── tokenStorage.ts               # ذخیره‌ی موقت توکن در localStorage
│   │   └── queryClient.ts
│   ├── types/
│   │   └── application.ts                # ستون‌های وضعیت + تایپ‌های کارت (منطبق بر بک‌اند)
│   ├── hooks/
│   ├── store/                             # Redux Toolkit (auth)
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── package.json
├── vite.config.ts
└── tailwind.config.js
```
