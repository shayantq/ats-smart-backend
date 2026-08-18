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

## سوییچر موقت بین دو پورتال

چون هنوز صفحه‌ی لاگین و مسیریابی بر اساس نقش کاربر ساخته نشده، `App.tsx` یک
سوییچر ساده (بدون URL Routing) بین «پورتال کارجو» و «داشبورد HR» نمایش می‌دهد؛
هر دو پورتال هم‌زمان در کد وجود دارند و فقط با کلیک روی تب بالای صفحه عوض می‌شوند.

## پورتال کارجو (Candidate Portal)

صفحه‌ی `src/pages/CandidatePortal.tsx` سه تب دارد:

- **پروفایل** (`ProfileTab.tsx`): ویرایش نام، نام‌خانوادگی، شماره تماس و
  تگ‌های مهارتی (`SkillTagInput.tsx`)، به‌همراه آپلود رزومه
  (`ResumeUploadWidget.tsx` — انتخاب آگهی مقصد + Drag & Drop فایل PDF/DOCX،
  ارسال ناهمگام به `POST /api/v1/resumes/upload` و نمایش فوری Toast موفقیت
  بدون قفل شدن صفحه).
- **پیگیری وضعیت** (`TrackerTab.tsx` + `ApplicationTrackerCard.tsx`): برای هر
  درخواست، یک نوار مرحله‌ای (Stepper) بصری نشان می‌دهد کارجو در کدام مرحله از
  ماشین وضعیت (`Draft` تا `Hired`) قرار دارد؛ حالت `Rejected` جدا و به‌صورت یک
  نشان قرمز نمایش داده می‌شود.
- **صندوق پیشنهادها** (`OffersTab.tsx` + `OfferCard.tsx`): فقط درخواست‌هایی با
  وضعیت `Offer` را نشان می‌دهد؛ دکمه‌های «قبول پیشنهاد» و «رد پیشنهاد» به
  `PUT /api/v1/candidates/me/applications/{id}/respond` وصل‌اند.

مثل داشبورد HR، چون صفحه‌ی لاگین واقعی هنوز نیست، یک فیلد موقت «توکن دسترسی»
بالای پورتال کارجو قرار دارد.

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
│   │   ├── KanbanBoard.tsx           # هماهنگ‌کننده‌ی بورد: fetch, drag&drop, snap-back, toast
│   │   └── candidate/                 # کامپوننت‌های پورتال کارجو
│   │       ├── SkillTagInput.tsx         # ورودی تگ‌های مهارتی
│   │       ├── ResumeUploadWidget.tsx     # انتخاب آگهی + Drag&Drop رزومه + آپلود ناهمگام
│   │       ├── ProfileTab.tsx              # ویرایش مشخصات فردی و مهارت‌ها
│   │       ├── ApplicationTrackerCard.tsx   # نوار مرحله‌ای بصری وضعیت یک درخواست
│   │       ├── TrackerTab.tsx                # لیست همه‌ی درخواست‌های کارجو
│   │       ├── OfferCard.tsx                  # کارت پیشنهاد + دکمه‌های قبول/رد
│   │       └── OffersTab.tsx                   # صندوق ورودی پیشنهادها
│   ├── context/
│   │   └── ToastContext.tsx           # سیستم Toast Notification (موفقیت/خطا)
│   ├── pages/
│   │   ├── HRDashboard.tsx             # صفحه‌ی داشبورد HR (فرم Job ID/Token موقت + بورد)
│   │   └── CandidatePortal.tsx          # صفحه‌ی پورتال کارجو (پروفایل/رهگیر/پیشنهادها)
│   ├── services/
│   │   ├── apiClient.ts                # fetch wrapper + apiUploadFile (multipart) + خطای تایپ‌شده
│   │   ├── applicationsApi.ts           # GET لیست و PUT تغییر وضعیت (سمت HR)
│   │   ├── candidatesApi.ts              # پروفایل، رهگیر، پیشنهادها، آپلود رزومه (سمت کارجو)
│   │   ├── jobsApi.ts                     # لیست آگهی‌های فعال (مسیر عمومی)
│   │   ├── tokenStorage.ts                 # ذخیره‌ی موقت توکن در localStorage
│   │   └── queryClient.ts
│   ├── types/
│   │   ├── application.ts                # ستون‌های وضعیت + تایپ‌های کارت (منطبق بر بک‌اند)
│   │   ├── candidate.ts                   # تایپ‌های پروفایل/رهگیر/پیشنهاد کارجو
│   │   └── job.ts                          # تایپ آگهی شغلی
│   ├── hooks/
│   ├── store/                             # Redux Toolkit (auth)
│   ├── App.tsx                             # سوییچر موقت بین دو پورتال
│   ├── main.tsx
│   └── index.css
├── package.json
├── vite.config.ts
└── tailwind.config.js
```
