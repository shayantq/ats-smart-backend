"""
ابزار رمزنگاری گذرواژه با الگوریتم Bcrypt.
Bcrypt به‌صورت خودکار برای هر گذرواژه یک Salt یکتا تولید می‌کند،
پس حتی دو کاربر با گذرواژه‌ی یکسان، دو رشته‌ی هش کاملاً متفاوت خواهند داشت.
"""

from passlib.context import CryptContext

# schemes=["bcrypt"] یعنی همیشه از Bcrypt استفاده شود.
# deprecated="auto" باعث می‌شود اگر در آینده الگوریتم عوض شد، هش‌های قدیمی هم قابل تشخیص بمانند.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """گذرواژه‌ی خام را به یک رشته‌ی هش‌شده و غیرقابل بازگشت تبدیل می‌کند."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """گذرواژه‌ی وارد شده توسط کاربر (مثلاً هنگام لاگین) را با هش ذخیره‌شده مقایسه می‌کند."""
    return pwd_context.verify(plain_password, password_hash)
