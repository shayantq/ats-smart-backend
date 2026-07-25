from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """کلاس پایه‌ی مشترک برای تمام مدل‌های ORM پروژه."""
    # این کلاس عمداً بدنه‌ای ندارد؛ فقط نقش یک نقطه‌ی اتصال مشترک
    # بین تمام مدل‌ها (User, Job, Application, ...) را دارد تا SQLAlchemy
    # بتواند همه‌ی جدول‌ها را زیر یک Metadata واحد بشناسد.
    pass
