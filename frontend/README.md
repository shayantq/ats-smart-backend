# ATS Smart — Frontend

رابط کاربری پلتفرم هوشمند جذب و استخدام، مبتنی بر React + TypeScript + Vite + Tailwind CSS.

این پوشه (`frontend/`) بخش فرانت‌اند پروژه است و کنار پوشه‌ی بک‌اند (`app/`) در همین ریپو قرار دارد.

## راه‌اندازی محیط توسعه

از ریشه‌ی ریپو، وارد این پوشه شوید:

```bash
cd frontend
npm install
```

## اجرای پروژه در حالت توسعه

```bash
npm run dev
```

سرور توسعه معمولاً روی آدرس زیر بالا می‌آید:
http://localhost:5173

## ساختار پروژه

```
frontend/
├── src/
│   ├── components/   # کامپوننت‌های قابل استفاده مجدد (دکمه، کارت، فرم و ...)
│   ├── pages/         # صفحات اصلی اپلیکیشن
│   ├── hooks/         # هوک‌های سفارشی React
│   ├── services/       # ارتباط با API بک‌اند
│   ├── App.tsx          # کامپوننت ریشه
│   ├── main.tsx          # نقطه ورود برنامه
│   └── index.css          # دایرکتیوهای Tailwind CSS
├── package.json
├── vite.config.ts
└── tailwind.config.js
```
