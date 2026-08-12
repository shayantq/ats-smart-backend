"""
ماشین وضعیت صلب (Strict State Machine) برای بورد کانبان فرآیند استخدام.

هدف: تضمین این‌که کارت یک درخواست (Application) فقط می‌تواند طبق ترتیب
استاندارد زیر جابه‌جا شود و هیچ پرش غیرقانونی (مثلاً از Screening مستقیم
به Hired) امکان‌پذیر نباشد.

ترتیب استاندارد مسیر (خطی):
    Draft -> Applied -> Screening -> Technical Interview -> HR Interview
    -> Offer -> Accepted -> Hired

از هر وضعیت غیرنهایی، همیشه دو مسیر مجاز وجود دارد:
    ۱. حرکت به وضعیت *بلافصل* بعدی در مسیر خطی بالا (بدون پرش از روی مراحل).
    ۲. رد شدن کارجو (انتقال به "Rejected") — که در هر مرحله از فرآیند
       (به‌جز حالت‌های نهایی) می‌تواند اتفاق بیفتد.

"Hired" و "Rejected" وضعیت‌های نهایی (Terminal) هستند: از این دو حالت
هیچ انتقال دیگری مجاز نیست (پرونده بسته شده است).
"""

from enum import Enum


class ApplicationStatus(str, Enum):
    """لیست کامل وضعیت‌های مجاز روی بورد کانبان."""

    DRAFT = "Draft"
    APPLIED = "Applied"
    SCREENING = "Screening"
    TECHNICAL_INTERVIEW = "Technical Interview"
    HR_INTERVIEW = "HR Interview"
    OFFER = "Offer"
    ACCEPTED = "Accepted"
    HIRED = "Hired"
    REJECTED = "Rejected"


# ترتیب خطی مسیر موفق (Rejected به‌عمد اینجا نیست؛ جدا مدیریت می‌شود)
_LINEAR_PATH: list[str] = [
    ApplicationStatus.DRAFT.value,
    ApplicationStatus.APPLIED.value,
    ApplicationStatus.SCREENING.value,
    ApplicationStatus.TECHNICAL_INTERVIEW.value,
    ApplicationStatus.HR_INTERVIEW.value,
    ApplicationStatus.OFFER.value,
    ApplicationStatus.ACCEPTED.value,
    ApplicationStatus.HIRED.value,
]

# وضعیت‌های نهایی: پس از رسیدن به این‌ها، پرونده بسته شده و دیگر قابل جابه‌جایی نیست
TERMINAL_STATUSES: frozenset[str] = frozenset({
    ApplicationStatus.HIRED.value,
    ApplicationStatus.REJECTED.value,
})


def get_allowed_next_statuses(current_status: str) -> frozenset[str]:
    """
    برای یک وضعیت فعلی، مجموعه‌ی وضعیت‌های *مجاز* بعدی را برمی‌گرداند.
    اگر current_status نامعتبر یا یکی از حالت‌های نهایی باشد، مجموعه‌ی خالی برمی‌گردد
    (یعنی هیچ انتقالی از آن مجاز نیست).
    """
    if current_status in TERMINAL_STATUSES:
        return frozenset()

    if current_status not in _LINEAR_PATH:
        return frozenset()

    allowed: set[str] = set()

    current_index = _LINEAR_PATH.index(current_status)
    next_index = current_index + 1
    if next_index < len(_LINEAR_PATH):
        allowed.add(_LINEAR_PATH[next_index])

    # از هر مرحله‌ی غیرنهایی، رد شدن کارجو همیشه یک مسیر مجاز است
    allowed.add(ApplicationStatus.REJECTED.value)

    return frozenset(allowed)


def is_transition_allowed(current_status: str, new_status: str) -> bool:
    """
    قانون اصلی ضدپرش (Anti-Skipping Rule):
    True فقط وقتی برمی‌گرداند که new_status دقیقاً یکی از مقادیر
    get_allowed_next_statuses(current_status) باشد.
    """
    return new_status in get_allowed_next_statuses(current_status)
