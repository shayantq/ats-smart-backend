"""ساخت کلید آزمایش محلی در مسیر ignored؛ هیچ کلید قبلی بازنویسی نمی‌شود."""

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    root = Path("secrets/inference")
    private, public = root / "worker.pem", root / "public/worker.pem"
    if private.exists() or public.exists():
        raise FileExistsError("کلید قبلی موجود است؛ بازنویسی خودکار مجاز نیست")
    public.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    private.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    public.write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    print("Local key files created; contents withheld.")


if __name__ == "__main__":
    main()
