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

## ورود و مسیریابی بر اساس نقش

- **صفحه‌ی ورود** (`src/pages/LoginPage.tsx`): ایمیل + رمز عبور → `POST /api/v1/auth/login` → ذخیره‌ی
  `access_token` (`tokenStorage.ts`) → `GET /api/v1/auth/me` → ثبت کاربر و نقشش در Redux (`authSlice`).
- `App.tsx` بر اساس نقش، کاربر را هدایت می‌کند: `Candidate` → پورتال کارجو، بقیه → داشبورد HR.
  سربرگ بالای صفحه ایمیل/نقش کاربر و دکمه‌ی «خروج» را نشان می‌دهد؛ با رفرش صفحه، نشست از روی
  توکن ذخیره‌شده بازیابی می‌شود.
- اگر توکن منقضی شود (پیش‌فرض ۱۵ دقیقه)، اولین درخواست با `401` رد و کاربر خودکار به صفحه‌ی ورود
  برگردانده می‌شود (`UNAUTHORIZED_EVENT` در `apiClient.ts`).
- در داشبورد HR، آگهی موردنظر از منوی «آگهی شغلی» (آگهی‌های فعال) انتخاب می‌شود.

## تست‌ها

```bash
npm test             # Jest: تست رندر کامپوننت‌ها (فایل‌های *.test.tsx کنار کامپوننت‌ها)
npm run test:e2e     # Playwright: شبیه‌سازی کاربر واقعی در مرورگر روی کل سیستم
npm run test:e2e:report   # گزارش HTML آخرین اجرای E2E
```

- **Jest + Testing Library** (`jest.config.cjs`، `src/test/`): رندر فرم ورود، بورد/ستون/کارت کانبان و
  مسیریابی `App` با `fetch` ساختگی — بدون نیاز به بک‌اند.
- **Playwright** (`playwright.config.ts`، `e2e/`): پیش‌نیاز: کل سیستم با `docker compose up -d` (از ریشه‌ی
  ریپو) در حال اجرا باشد (`http://localhost:8080`، قابل تغییر با `E2E_BASE_URL`).
  - داده‌ی آزمایشی (یک HR، یک آگهی، سه کارجو) قبل از اجرا داخل کانتینر بک‌اند ساخته و بعد از اجرا دقیقاً
    همان پاک می‌شود (`e2e/seed_e2e_data.py`).
  - سناریوها: ورود با فرم و لود بورد، ترتیب ستون‌ها و جای کارت‌ها، درگ‌ودراپ مجاز (با بررسی ماندگاری بعد
    از رفرش)، درگ‌ودراپ غیرمجاز (برگشت کارت + پیام خطا)، رمز اشتباه، فیلد خالی، خروج.
  - هر خطای جاوااسکریپت/کرش مرورگر، تست را Fail می‌کند (`e2e/fixtures.ts`).
  - مرورگر لوکال: Microsoft Edge نصب‌شده روی سیستم (بدون دانلود مرورگر جدا)؛ در CI: Chromium خودِ
    Playwright. با `E2E_BROWSER_CHANNEL` قابل تغییر است.

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

## پورتال ثبت نمرات و ارزیابی مصاحبه (Interview Evaluation)

داخل `HRDashboard.tsx` یک تب داخلی دوم («مصاحبه‌های امروز») اضافه شده،
کنار تب «بورد کانبان» موجود:

- **`TodayInterviewsPanel.tsx`**: لیست مصاحبه‌های امروز (`GET /interviews/?date=...`)
  را نشان می‌دهد؛ یک دکمه هم برای دیدن «همه‌ی فرم‌های ارزیابی معوقه»
  (`?status=Pending`، صرف‌نظر از تاریخ) وجود دارد تا دسترسی سریع به فرم‌های
  عقب‌افتاده ممکن باشد.
- **`InterviewRow.tsx`**: هر ردیف یک مصاحبه — اگر `status` آن `Completed`
  باشد فقط خلاصه‌ی نمره را نشان می‌دهد، وگرنه دکمه‌ی «ثبت ارزیابی» فرم را
  باز/بسته می‌کند.
- **`EvaluationForm.tsx`**: فیلدهای عددی (Range Slider، ۱ تا ۱۰) برای هر
  معیار نمره‌دهی (`technical_skill`, `problem_solving`, `communication`,
  `culture_fit` — دقیقاً همان مجموعه‌ای که بک‌اند می‌پذیرد) + یک فیلد متنی
  برای بازخورد کیفی. ثبت با `PUT /interviews/{id}/evaluation` (از طریق
  React Query `useMutation`) انجام می‌شود؛ بعد از موفقیت، Toast نمایش داده
  می‌شود و لیست مصاحبه‌ها بدون رفرش صفحه دوباره خوانده می‌شود (invalidate
  شدن Query)، پس وضعیت آن ردیف فوراً به «تکمیل شده» تغییر می‌کند.

## داشبورد تحلیلی (Analytics Dashboard)

داخل `HRDashboard.tsx` یک تب داخلی سوم («داشبورد تحلیلی») اضافه شده، کنار
«بورد کانبان» و «مصاحبه‌های امروز» — چون هنوز صفحه‌ی جدای «پنل ادمین» ساخته
نشده، مثل تسک قبلی همین‌جا (داشبورد HR/Admin موجود) اضافه شد:

- **`AnalyticsDashboard.tsx`**: هماهنگ‌کننده‌ی دو کارت نمودار، هرکدام با
  `useQuery` جدا (کند بودن یکی دیگری را بلاک نمی‌کند)، دکمه‌ی «به‌روزرسانی»
  دستی برای هرکدام، انتخاب بازه‌ی زمانی (۷/۳۰/۹۰ روز) برای نمودار روند، و
  یک چک‌باکس اختیاری برای محدود کردن هر دو نمودار به همان Job ID که در
  فیلد موقت بالای داشبورد وارد شده.
- **`RecruitmentFunnelChart.tsx`**: نمودار قیف (`GET /analytics/funnel`) با
  کتابخانه‌ی **Recharts**؛ برچسب هر مرحله از همان `STATUS_COLUMNS` موجود
  (`types/application.ts`) خوانده می‌شود تا با بورد کانبان یکدست بماند.
  Tooltip هر مرحله، هم تعداد و هم نرخ تبدیل (نسبت به مرحله‌ی قبل و نسبت به
  ابتدای قیف) را نشان می‌دهد.
- **`ApplicationsTrendChart.tsx`**: نمودار خطی (`GET
  /analytics/applications-trend`) با Recharts؛ محور افقی و Tooltip با
  `toLocaleDateString("fa-IR")` فرمت می‌شوند (همان الگوی بقیه‌ی تاریخ‌های
  پروژه).
- **`ChartSkeleton.tsx`**: اسکلتون بارگذاری عمومی (Tailwind
  `animate-pulse`) — طبق معیار پذیرش تسک، به‌جای متن ساده‌ی «در حال
  بارگذاری...» در زمان Fetch نمایش داده می‌شود.

⚠️ **نکته‌ی فنی مهم:** هر دو نمودار داخل یک ظرف `dir="ltr"` رندر می‌شوند.
Recharts رسماً از چیدمان RTL پشتیبانی نمی‌کند (محاسبه‌ی مختصات Tooltip/Hover
زیر والد RTL درست کار نمی‌کند)؛ این فقط جهت چیدمان داخلی SVG را عوض
می‌کند، متن‌های فارسی داخل Tooltip/برچسب‌ها طبق جهت طبیعی خودشان درست
نمایش داده می‌شوند.



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
│   │   ├── candidate/                 # کامپوننت‌های پورتال کارجو
│   │   │   ├── SkillTagInput.tsx         # ورودی تگ‌های مهارتی
│   │   │   ├── ResumeUploadWidget.tsx     # انتخاب آگهی + Drag&Drop رزومه + آپلود ناهمگام
│   │   │   ├── ProfileTab.tsx              # ویرایش مشخصات فردی و مهارت‌ها
│   │   │   ├── ApplicationTrackerCard.tsx   # نوار مرحله‌ای بصری وضعیت یک درخواست
│   │   │   ├── TrackerTab.tsx                # لیست همه‌ی درخواست‌های کارجو
│   │   │   ├── OfferCard.tsx                  # کارت پیشنهاد + دکمه‌های قبول/رد
│   │   │   └── OffersTab.tsx                   # صندوق ورودی پیشنهادها
│   │   ├── interview/                 # کامپوننت‌های پورتال ارزیابی مصاحبه
│   │   │   ├── TodayInterviewsPanel.tsx  # لیست مصاحبه‌های امروز/معوقه (React Query)
│   │   │   ├── InterviewRow.tsx           # یک ردیف: خلاصه‌ی نمره یا دکمه‌ی «ثبت ارزیابی»
│   │   │   └── EvaluationForm.tsx          # فرم نمرات عددی (Slider) + بازخورد کیفی
│   │   └── analytics/                 # کامپوننت‌های داشبورد تحلیلی
│   │       ├── AnalyticsDashboard.tsx    # هماهنگ‌کننده: دو useQuery جدا + دکمه‌ی رفرش + انتخاب بازه
│   │       ├── RecruitmentFunnelChart.tsx # نمودار قیف (Recharts) + Tooltip نرخ تبدیل
│   │       ├── ApplicationsTrendChart.tsx  # نمودار خطی روند ثبت درخواست (Recharts)
│   │       └── ChartSkeleton.tsx            # اسکلتون بارگذاری عمومی (Tailwind animate-pulse)
│   ├── context/
│   │   └── ToastContext.tsx           # سیستم Toast Notification (موفقیت/خطا)
│   ├── pages/
│   │   ├── LoginPage.tsx               # صفحه‌ی ورود (ایمیل + رمز عبور)
│   │   ├── HRDashboard.tsx             # داشبورد HR (انتخاب آگهی + کانبان + مصاحبه‌ها + تحلیل + اعلان‌ها)
│   │   └── CandidatePortal.tsx          # صفحه‌ی پورتال کارجو (پروفایل/رهگیر/پیشنهادها)
│   ├── services/
│   │   ├── apiClient.ts                # fetch wrapper + apiUploadFile (multipart) + خطای تایپ‌شده
│   │   ├── analyticsApi.ts              # قیف استخدام + سری زمانی ثبت درخواست‌ها
│   │   ├── applicationsApi.ts           # GET لیست و PUT تغییر وضعیت (سمت HR)
│   │   ├── candidatesApi.ts              # پروفایل، رهگیر، پیشنهادها، آپلود رزومه (سمت کارجو)
│   │   ├── interviewsApi.ts               # لیست مصاحبه‌ها (فیلترپذیر) + ثبت ارزیابی
│   │   ├── jobsApi.ts                     # لیست آگهی‌های فعال (مسیر عمومی)
│   │   ├── authApi.ts                      # ورود + اطلاعات کاربر جاری (/auth/me)
│   │   ├── tokenStorage.ts                 # نگه‌داری access_token در localStorage
│   │   └── queryClient.ts
│   ├── types/
│   │   ├── analytics.ts                  # تایپ قیف استخدام + سری زمانی (منطبق بر بک‌اند)
│   │   ├── application.ts                # ستون‌های وضعیت + تایپ‌های کارت (منطبق بر بک‌اند)
│   │   ├── candidate.ts                   # تایپ‌های پروفایل/رهگیر/پیشنهاد کارجو
│   │   ├── interview.ts                    # تایپ مصاحبه + معیارهای نمره‌دهی
│   │   └── job.ts                          # تایپ آگهی شغلی
│   ├── hooks/
│   ├── store/                             # Redux Toolkit (auth)
│   ├── test/                              # ابزارهای مشترک تست‌های Jest
│   ├── App.tsx                             # بازیابی نشست + مسیریابی بر اساس نقش + خروج
│   ├── main.tsx
│   └── index.css
├── e2e/                                   # سناریوهای Playwright + داده‌ی آزمایشی
├── playwright.config.ts · jest.config.cjs
├── package.json
├── vite.config.ts
└── tailwind.config.js
```
