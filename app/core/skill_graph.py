"""
گراف مهارت (Skill Ontology/Graph): نگاشت مهارت‌های زیرمجموعه/مترادف به مهارت اصلی.

مثال: «FastAPI» و «Django» هر دو زیرشاخه‌ی «Python» هستند؛ اگر متن رزومه فقط
به «FastAPI» اشاره کرده باشد، سیستم باید تشخیص دهد که کارجو با «Python» هم
آشناست (چون FastAPI یک فریم‌ورک مبتنی بر Python است) — این دقیقاً همان
«تطبیق و همپوشانی مترادف‌ها»ی خواسته‌شده در معیار پذیرش تسک است.

ساختار: هر کلید یک «مهارت اصلی» (گره ریشه) است و مقدارش لیست «مهارت‌های
زیرمجموعه» (گره‌های فرزند) آن است. تابع match_skills این ساختار را به یک
جدول جست‌وجوی مسطح تبدیل می‌کند و متن رزومه را برای همه‌ی گره‌های این گراف
اسکن می‌کند — اگر یک زیرشاخه پیدا شود، هم خودش و هم مهارت اصلی‌اش (گره
والد) به نتیجه اضافه می‌شوند.
"""

import re

SKILL_ONTOLOGY: dict[str, list[str]] = {
    "Python": ["FastAPI", "Django", "Flask", "Pandas", "NumPy", "PyTest", "SQLAlchemy"],
    "JavaScript": [
        "TypeScript",
        "React",
        "React.js",
        "Vue.js",
        "Angular",
        "Node.js",
        "Express.js",
        "Next.js",
    ],
    "Java": ["Spring", "Spring Boot", "Hibernate"],
    "C#": ["ASP.NET", ".NET Core"],
    "SQL": [
        "PostgreSQL",
        "MySQL",
        "SQL Server",
        "SQLite",
        "Oracle Database",
    ],
    "NoSQL": ["MongoDB", "Redis", "Cassandra", "Elasticsearch"],
    "DevOps": ["Docker", "Kubernetes", "Jenkins", "Terraform", "Ansible", "CI/CD"],
    "Cloud Computing": ["AWS", "Azure", "GCP", "Google Cloud"],
    "Machine Learning": ["Deep Learning", "PyTorch", "TensorFlow", "Scikit-learn", "Keras"],
    "Project Management": ["Scrum", "Agile", "Kanban", "Jira"],
    "UI/UX Design": ["Figma", "Adobe XD", "Sketch"],
}


def _build_lookup_table() -> dict[str, tuple[str, str]]:
    """
    گراف بالا را به یک جدول جست‌وجوی مسطح تبدیل می‌کند:
    کلید = نسخه‌ی حروف‌کوچک هر مهارت (برای جست‌وجوی غیرحساس به بزرگ/کوچکی حروف)
    مقدار = (نام نمایشی همان مهارت، نام مهارت اصلی/گره والد آن در گراف)

    خودِ مهارت اصلی هم به خودش نگاشت می‌شود تا اگر متن مستقیماً همان مهارت
    اصلی (مثلاً «Python») را هم داشته باشد، جدا شناسایی شود.
    """
    lookup: dict[str, tuple[str, str]] = {}
    for core_skill, sub_skills in SKILL_ONTOLOGY.items():
        lookup[core_skill.lower()] = (core_skill, core_skill)
        for sub_skill in sub_skills:
            lookup[sub_skill.lower()] = (sub_skill, core_skill)
    return lookup


_SKILL_LOOKUP_TABLE = _build_lookup_table()

# مرز کلمه: قبل/بعد از کلیدواژه نباید حرف یا رقم دیگری چسبیده باشد — تا مثلاً
# «java» به‌اشتباه داخل «javascript» تشخیص داده نشود.
_NON_WORD_BOUNDARY = r"(?<![a-zA-Z0-9])"
_NON_WORD_BOUNDARY_END = r"(?![a-zA-Z0-9])"


def match_skills(text: str) -> list[str]:
    """
    متن رزومه را برای همه‌ی گره‌های گراف مهارت اسکن می‌کند. برای هر مورد پیدا
    شده، هم خودِ همان مهارت (اگر زیرشاخه بود) و هم مهارت اصلی/گره والدش به
    نتیجه اضافه می‌شوند (بدون تکرار) — طبق مثال FastAPI/Django -> Python.

    خروجی به‌صورت الفبایی مرتب است تا نتیجه‌ی این تابع همیشه Deterministic
    (قابل تکرار و قابل تست) باشد.
    """
    if not text:
        return []

    lowered_text = text.lower()
    detected_skills: set[str] = set()

    for keyword, (display_name, core_skill) in _SKILL_LOOKUP_TABLE.items():
        pattern = _NON_WORD_BOUNDARY + re.escape(keyword) + _NON_WORD_BOUNDARY_END
        if re.search(pattern, lowered_text):
            detected_skills.add(display_name)
            detected_skills.add(core_skill)

    return sorted(detected_skills)


def get_core_skill(skill_name: str) -> str:
    """
    اگر skill_name (زیرشاخه یا خودِ مهارت اصلی) در گراف مهارت شناخته‌شده باشد،
    نام مهارت اصلی/گره والدش را برمی‌گرداند؛ در غیر این صورت خودِ ورودی را
    بدون تغییر پس می‌دهد (برای مهارت‌هایی خارج از گراف، مثل «Photoshop»).

    این تابع توسط موتور نمره‌دهی (app/core/matching_engine.py) استفاده می‌شود
    تا مهارت اجباری آگهی («Python») را حتی وقتی کارجو فقط زیرشاخه‌اش
    («FastAPI») را ذکر کرده، تطبیق‌یافته تشخیص دهد.
    """
    if not skill_name:
        return skill_name

    entry = _SKILL_LOOKUP_TABLE.get(skill_name.strip().lower())
    return entry[1] if entry else skill_name
