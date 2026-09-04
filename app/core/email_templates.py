"""
موتور Render قالب‌های ایمیل (Jinja2).

قالب‌های HTML در app/templates/emails/ نگه‌داری می‌شوند (base.html به‌عنوان
Layout مشترک، و بقیه با extends آن را گسترش می‌دهند). این ماژول قالب مشخص‌شده
را با مقادیر واقعی (نام کارجو، عنوان شغل، کد OTP و ...) جایگذاری (Render)
می‌کند و HTML نهایی را برمی‌گرداند.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_email_template(template_name: str, **context: object) -> str:
    """
    قالب مشخص‌شده (مثلاً "job_offer.html") را با مقادیر context جایگذاری
    می‌کند. چون autoescape فعال است، مقادیر متغیر (مثل نام کارجو) خودکار از
    نظر HTML امن (Escape) می‌شوند — یک محتوای مخرب در نام کاربر نمی‌تواند
    ساختار ایمیل را بشکند.
    """
    template = _jinja_env.get_template(template_name)
    return template.render(**context)
