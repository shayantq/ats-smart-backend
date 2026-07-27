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

## مدیریت وضعیت (State Management)

- **Redux Toolkit**: برای وضعیت های سراسری اپلیکیشن (فعلاً فقط اطلاعات کاربر لاگین شده در `store/slices/authSlice.ts`). به‌جای `useDispatch`/`useSelector` خام، همیشه از هوک های تایپ‌شده در `store/hooks.ts` استفاده کنید.
- **React Query**: برای گرفتن و کش کردن داده از بک اند (تنظیماتش در `services/queryClient.ts`).

هر دو Provider در `main.tsx` دور کامپوننت اصلی (`App`) پیچیده شده اند.

برای دیدن وضعیت Store در مرورگر، اکستنشن Redux DevTools را نصب کنید.

## ساختار پروژه

```
frontend/
├── src/
│   ├── components/     # کامپوننت‌های قابل استفاده مجدد (دکمه، کارت، فرم و ...)
│   ├── pages/            # صفحات اصلی اپلیکیشن
│   ├── hooks/             # هوک‌های سفارشی React
│   ├── services/           # ارتباط با API بک‌اند + تنظیمات React Query
│   │   └── queryClient.ts
│   ├── store/               # مدیریت وضعیت سراسری با Redux Toolkit
│   │   ├── store.ts
│   │   ├── hooks.ts
│   │   └── slices/
│   │       └── authSlice.ts
│   ├── App.tsx               # کامپوننت ریشه
│   ├── main.tsx               # نقطه ورود برنامه (Provider های Redux و React Query اینجا هستند)
│   └── index.css               # دایرکتیوهای Tailwind CSS
├── package.json
├── vite.config.ts
└── tailwind.config.js
```
