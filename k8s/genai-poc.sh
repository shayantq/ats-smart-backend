#!/usr/bin/env bash
# =============================================================================
# اثبات مفهوم سرتاسری تولید سؤال مصاحبه با هوش مصنوعی مولد — از مسیر واقعی API داخل کلاستر
#
#   bash k8s/genai-poc.sh                    رزومه و آگهی نمونه‌ی docs/genai/samples
#   QUESTIONS=8 LANGUAGE=en bash k8s/genai-poc.sh
#   RESUME=path/to/cv.txt JOB=path/to/job.json bash k8s/genai-poc.sh
#   KEEP_DATA=1 ...                          داده‌های آزمایشی (و بانک سؤال) پس از اجرا پاک نشوند
#
#   ۱. آگهی نمونه ساخته و رزومه‌ی نمونه (DOCX) با POST /api/v1/resumes/upload آپلود می‌شود
#   ۲. منتظر خط لوله‌ی رزومه (OCR/NER ← موتور مهارت ← نمره‌ی تطابق) در resume-worker
#   ۳. POST /api/v1/genai/interview-questions (۲۰۲) ← genai-worker ← سرویس مدل زبانی
#   ۴. Polling وضعیت تا completed و نمایش سؤال‌های ساخت‌یافته + کلید پاسخ
#   ۵. تأیید یک سؤال (PATCH) و جست‌وجوی آن در بانک سؤال مشترک
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1

if grep -qi microsoft /proc/version 2>/dev/null && command -v kubectl.exe >/dev/null 2>&1; then
    kubectl() { kubectl.exe "$@"; }
fi
command -v kubectl >/dev/null 2>&1 || { echo "kubectl پیدا نشد" >&2; exit 2; }

cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-ats-smart}"
RESUME="${RESUME:-docs/genai/samples/resume-backend.txt}"
JOB="${JOB:-docs/genai/samples/job-senior-backend.json}"
QUESTIONS="${QUESTIONS:-6}"
LANGUAGE="${LANGUAGE:-fa}"
RUN_ID="$(date +%Y%m%d%H%M%S)"
REPORT_DIR="k8s/loadtest/reports"
REPORT="${REPORT_DIR}/genai-poc-${RUN_ID}.log"
RESULT_JSON="${REPORT_DIR}/genai-poc-${RUN_ID}.json"
mkdir -p "$REPORT_DIR"

PYTHON=""
for candidate in python3 python; do
    if "$candidate" -c "import json" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
[[ -n "$PYTHON" ]] || { echo "Python روی این سیستم پیدا نشد" >&2; exit 2; }
b64() { "$PYTHON" -c "import base64, sys; print(base64.b64encode(open(sys.argv[1], 'rb').read()).decode())" "$1"; }

printf '\033[1mATS Smart — اثبات مفهوم تولید سؤال مصاحبه (GenAI)\033[0m\n' | tee "$REPORT"
printf 'context: %s · %s · رزومه: %s · آگهی: %s · %s سؤال (%s)\n' "$(kubectl config current-context)" \
    "$(date '+%Y-%m-%d %H:%M:%S')" "$RESUME" "$JOB" "$QUESTIONS" "$LANGUAGE" | tee -a "$REPORT"

kubectl -n "$NAMESPACE" exec -i deploy/backend-api -c backend-api -- env \
    RUN_ID="$RUN_ID" RESUME_B64="$(b64 "$RESUME")" RESUME_NAME="$(basename "$RESUME")" JOB_B64="$(b64 "$JOB")" \
    QUESTIONS="$QUESTIONS" LANGUAGE="$LANGUAGE" KEEP_DATA="${KEEP_DATA:-0}" python - <<'PY' 2>&1 | tee -a "$REPORT"
import asyncio, base64, io, json, os, sys, time

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.models import Application, Job, User

RUN = os.environ["RUN_ID"]
API = "http://127.0.0.1:8000/api/v1"
failures = 0


def step(title: str) -> None:
    print(f"\n━━━ {title} ━━━", flush=True)


def ok(message: str) -> None:
    print(f"  ✔ PASS  {message}", flush=True)


def fail(message: str) -> None:
    global failures
    failures += 1
    print(f"  ✘ FAIL  {message}", flush=True)


def headers(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))[0]}"}


def resume_upload(name: str, data: bytes) -> tuple[str, bytes, str]:
    """متن ساده به DOCX واقعی تبدیل می‌شود (مسیر آپلود فقط PDF/DOCX می‌پذیرد)."""
    if not name.lower().endswith(".txt"):
        kind = "application/pdf" if name.lower().endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return name, data, kind
    from docx import Document

    document = Document()
    for line in data.decode("utf-8").splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return name.rsplit(".", 1)[0] + ".docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def main() -> int:
    step("پیش‌نیازها")
    if not settings.genai_enabled:
        fail("سرویس مدل زبانی پیکربندی نشده (k8s/overlays/local/secrets/genai.env)")
        return 1
    ok(f"سرویس مدل زبانی: {settings.GENAI_BASE_URL} · مدل «{settings.GENAI_MODEL}» · خروجی {settings.GENAI_STRUCTURED_OUTPUT}")

    job_spec = json.loads(base64.b64decode(os.environ["JOB_B64"]))
    async with AsyncSessionLocal() as session:
        hr = User(email=f"genai-poc-hr-{RUN}@example.com", password_hash="!", role="HR_Manager")
        candidate = User(email=f"genai-poc-cand-{RUN}@example.com", password_hash="!", role="Candidate")
        session.add_all([hr, candidate])
        await session.flush()
        job = Job(created_by=hr.id, status="Active", **{**job_spec, "title": f"[GenAI-PoC {RUN}] {job_spec['title']}"})
        session.add(job)
        await session.commit()
        hr_id, candidate_id, job_id = hr.id, candidate.id, job.id

    async with httpx.AsyncClient(base_url=API, timeout=60) as client:
        step("۱. آپلود رزومه‌ی نمونه از مسیر واقعی API")
        name, data, kind = resume_upload(os.environ["RESUME_NAME"], base64.b64decode(os.environ["RESUME_B64"]))
        response = await client.post(
            "/resumes/upload", data={"job_id": str(job_id)}, files={"file": (name, data, kind)}, headers=headers(candidate_id)
        )
        if response.status_code != 202:
            fail(f"آپلود رزومه: {response.status_code} {response.text[:200]}")
            return 1
        ok(f"رزومه آپلود شد ({name}، {len(data)} بایت) — پاسخ 202")

        step("۲. پردازش رزومه در resume-worker (استخراج متن ← NER ← موتور مهارت ← نمره‌ی تطابق)")
        application_id, started = None, time.monotonic()
        while time.monotonic() - started < 300:
            async with AsyncSessionLocal() as session:
                row = (await session.execute(text(
                    "select a.id, a.score_ai from applications a where a.job_id = :job and a.score_ai is not null"
                ), {"job": job_id})).first()
            if row:
                application_id, score = row
                break
            await asyncio.sleep(2)
        if application_id is None:
            fail("رزومه در ۵ دقیقه پردازش نشد")
            return 1
        ok(f"رزومه پردازش شد در {time.monotonic() - started:.0f} ثانیه — نمره‌ی تطابق: {score}")

        step("۳. درخواست تولید سؤال (POST /genai/interview-questions)")
        response = await client.post(
            "/genai/interview-questions",
            json={"application_id": str(application_id), "question_count": int(os.environ["QUESTIONS"]),
                  "language": os.environ["LANGUAGE"], "difficulty": "mixed"},
            headers=headers(hr_id),
        )
        if response.status_code != 202:
            fail(f"درخواست تولید: {response.status_code} {response.text[:300]}")
            return 1
        accepted = response.json()
        ok(f"پاسخ 202 — بانک سؤال {accepted['id']} در صف genai")

        step("۴. پیگیری وضعیت تا پایان تولید (genai-worker ← مدل زبانی)")
        print("          (مدل روی CPU: ۶ سؤال حدود ۵ تا ۹ دقیقه طول می‌کشد)", flush=True)
        started, last_status, last_print, result = time.monotonic(), None, 0.0, None
        while time.monotonic() - started < 900:
            result = (await client.get(accepted["status_url"].removeprefix("/api/v1"), headers=headers(hr_id))).json()
            elapsed = time.monotonic() - started
            # هر ۳۰ ثانیه یک خط پیشرفت، تا انتظار طولانی با گیر کردن اشتباه گرفته نشود
            if result["status"] != last_status or elapsed - last_print >= 30:
                print(f"          {elapsed:5.0f}s  وضعیت: {result['status']}", flush=True)
                last_status, last_print = result["status"], elapsed
            if result["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(5)
        if result is None or result["status"] != "completed":
            fail(f"تولید سؤال کامل نشد: {result and result.get('status')} — {result and result.get('error')}")
            return 1
        usage = result["usage"]
        ok(f"{len(result['questions'])} سؤال ساخت‌یافته در {usage['latency_ms'] / 1000:.1f} ثانیه "
           f"(توکن ورودی/خروجی {usage['prompt_tokens']}/{usage['completion_tokens']})")
        print(f"\n          محورهای مصاحبه: {result['focus_summary']}\n", flush=True)
        for question in result["questions"]:
            print(f"  {question['position']:>2}. [{question['category']} · {question['difficulty']} · {question['skill']}]", flush=True)
            print(f"      سؤال:        {question['question']}", flush=True)
            print(f"      هدف:         {question['purpose']}", flush=True)
            print(f"      کلید پاسخ:   {question['expected_answer'][:300]}", flush=True)
            print(f"      معیارها:     {' · '.join(question['evaluation_points'])}", flush=True)
            if question["red_flags"]:
                print(f"      نشانه‌ی خطر: {' · '.join(question['red_flags'])}", flush=True)
        categories = {question["category"] for question in result["questions"]}
        ok(f"دسته‌بندی‌ها: {', '.join(sorted(categories))}")
        if "gap_probe" in categories:
            ok("حداقل یک سؤال برای سنجش شکاف‌های کارجو (gap_probe) ساخته شد")
        else:
            fail("هیچ سؤال gap_probe برای شکاف‌ها ساخته نشد")

        step("۵. بازبینی مصاحبه‌کننده و بانک سؤال مشترک")
        first = result["questions"][0]
        patched = await client.patch(
            f"/genai/interview-questions/{result['id']}/questions/{first['id']}",
            json={"is_approved": True, "interviewer_notes": "تأیید در اجرای PoC"},
            headers=headers(hr_id),
        )
        bank = (await client.get("/genai/question-bank", params={"skill": first["skill"]}, headers=headers(hr_id))).json()
        if patched.status_code == 200 and any(item["id"] == first["id"] for item in bank["items"]):
            ok(f"سؤال ۱ تأیید شد و در بانک سؤال مشترک با مهارت «{first['skill']}» پیدا شد")
        else:
            fail(f"تأیید/بانک سؤال: {patched.status_code} {bank}")
        print("RESULT_JSON " + json.dumps(result, ensure_ascii=False), flush=True)

    if os.environ.get("KEEP_DATA") != "1":
        async with AsyncSessionLocal() as session:
            users = f"(select id from users where email like 'genai-poc-%-{RUN}@example.com')"
            candidates = f"(select id from candidates where user_id in {users})"
            for statement in (
                f"delete from interview_question_sets where job_id = '{job_id}'",
                f"delete from status_history where application_id in (select id from applications where job_id = '{job_id}')",
                f"delete from applications where job_id = '{job_id}'",
                f"delete from resumes where candidate_id in {candidates}",
                f"delete from candidates where user_id in {users}",
                f"delete from jobs where id = '{job_id}'",
                f"delete from users where email like 'genai-poc-%-{RUN}@example.com'",
            ):
                await session.execute(text(statement))
            await session.commit()
        print("\n          داده‌های آزمایشی حذف شدند (KEEP_DATA=1 برای نگه‌داشتن)", flush=True)
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
PY
status=${PIPESTATUS[0]}
grep '^RESULT_JSON ' "$REPORT" | sed 's/^RESULT_JSON //' >"$RESULT_JSON"
sed -i '/^RESULT_JSON /d' "$REPORT"
printf '          خروجی JSON کامل: %s · گزارش: %s\n' "$RESULT_JSON" "$REPORT" | tee -a "$REPORT"
if [[ "$status" == "0" ]]; then
    printf '\n\033[1;32m[GENAI POC PASS] رزومه + آگهی ← فهرست ساخت‌یافته‌ی سؤال‌های مصاحبه\033[0m\n' | tee -a "$REPORT"
else
    printf '\n\033[1;31m[GENAI POC FAIL]\033[0m\n' | tee -a "$REPORT"
fi
exit "$status"
