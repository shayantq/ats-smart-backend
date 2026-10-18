#!/usr/bin/env bash
# =============================================================================
# سنجش ایندکس‌های GIN جستجوی کارجویان در حجم بالای رزومه (مایگریشن 9c4e2a7b1d35)
#
#   bash k8s/search-benchmark.sh                 پیش‌فرض: ۲۰٬۰۰۰ رزومه‌ی آزمایشی
#   RESUMES=100000 bash k8s/search-benchmark.sh
#   KEEP_DATA=1 ...                              داده‌های آزمایشی پس از سنجش پاک نشوند
#
# ۱. ساخت حجم بالای رزومه‌ی آزمایشی با generate_series (مهارت‌ها، سابقه و متن تصادفی)
# ۲. EXPLAIN ANALYZE شرط مهارت به دو شکل — هر دو دقیقاً یک نتیجه را برمی‌گردانند:
#      قبلی:  EXISTS (jsonb_array_elements_text(...) ... lower(e) = lower(:skill))   ← Seq Scan روی کل جدول
#      جدید:  ats_resume_skill_keys(skill_analysis) @> ARRAY[lower(:skill)]           ← Bitmap Index Scan (GIN)
# ۳. همین مقایسه برای فیلتر سابقه، و زمان پاسخ واقعی API جستجو (/api/v1/candidates/search/)
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1

if grep -qi microsoft /proc/version 2>/dev/null && command -v kubectl.exe >/dev/null 2>&1; then
    kubectl() { kubectl.exe "$@"; }
fi
command -v kubectl >/dev/null 2>&1 || { echo "kubectl پیدا نشد" >&2; exit 2; }

cd "$(dirname "$0")/.."

NAMESPACE="${NAMESPACE:-ats-smart}"
RESUMES="${RESUMES:-20000}"
REPORT_DIR="k8s/loadtest/reports"
REPORT="${REPORT_DIR}/search-benchmark-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$REPORT_DIR"

PASSED=0
FAILED=0
section() { printf '\n\033[1;34m━━━ %s ━━━\033[0m\n' "$*" | tee -a "$REPORT"; }
pass() { PASSED=$((PASSED + 1)); printf '  \033[32m✔ PASS\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
fail() { FAILED=$((FAILED + 1)); printf '  \033[31m✘ FAIL\033[0m  %s\n' "$*" | tee -a "$REPORT"; }
info() { printf '          %s\n' "$*" | tee -a "$REPORT"; }
k() { kubectl -n "$NAMESPACE" "$@"; }
sql() { k exec -i postgres-0 -c postgres -- sh -c 'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d smart_ats_db'; }

printf '\033[1mATS Smart — سنجش ایندکس‌های GIN جستجوی کارجویان\033[0m\n' | tee "$REPORT"
printf 'context: %s · %s · %s رزومه‌ی آزمایشی\n' "$(kubectl config current-context)" "$(date '+%Y-%m-%d %H:%M:%S')" "$RESUMES" | tee -a "$REPORT"

# =============================================================================
section "ایندکس‌های جدول resumes"
# =============================================================================
sql <<'SQL' | sed 's/^/  /' | tee -a "$REPORT"
select indexname || '  →  ' || regexp_replace(indexdef, '^.* USING ', 'USING ') from pg_indexes where tablename = 'resumes' order by 1;
SQL
[[ "$(echo "select count(*) from pg_indexes where indexname = 'ix_resumes_skill_keys_gin'" | sql)" == "1" ]] \
    && pass "ایندکس GIN مهارت‌ها (ix_resumes_skill_keys_gin) و تابع ats_resume_skill_keys موجودند" \
    || { fail "مایگریشن 9c4e2a7b1d35 اجرا نشده (bash k8s/deploy.sh)"; exit 1; }

# =============================================================================
section "ساخت ${RESUMES} رزومه‌ی آزمایشی"
# =============================================================================
started=$SECONDS
sql <<SQL
-- ۳۰ مهارت پرکاربرد هر کدام با احتمال ۱۵٪ در هر رزومه، و «Elixir» نادر (۰.۵٪) — مثل یک مهارت تخصصی
-- که کارشناس منابع انسانی دنبالش می‌گردد. ارجاع 0 * g زیرپرس‌وجو را برای هر ردیف جداگانه اجرا می‌کند.
create temporary table bench_seed as select g from generate_series(1, ${RESUMES}) as g;
insert into users (id, email, password_hash, role, is_active)
select gen_random_uuid(), 'bench-' || g || '@example.com', '!', 'Candidate', true from bench_seed;
insert into candidates (id, user_id, first_name, last_name)
select gen_random_uuid(), u.id, 'کارجو', 'آزمایشی' from users u where u.email like 'bench-%@example.com';
insert into resumes (id, candidate_id, file_url, raw_text, skill_analysis)
select gen_random_uuid(), c.id, 'bench://resume',
       'Experienced engineer working with distributed systems, APIs and databases',
       jsonb_build_object(
           'skills', coalesce((
               select jsonb_agg(skill) from unnest(array[
                   'Python', 'Django', 'FastAPI', 'Flask', 'JavaScript', 'TypeScript', 'React', 'Vue', 'Node.js',
                   'Java', 'Spring', 'Go', 'C#', 'ASP.NET', 'PHP', 'Laravel', 'PostgreSQL', 'MySQL', 'MongoDB',
                   'Redis', 'Docker', 'Kubernetes', 'AWS', 'Linux', 'Git', 'GraphQL', 'Kafka', 'RabbitMQ',
                   'Terraform', 'Ansible']) as skill
               where random() < 0.15 + 0 * length(c.first_name)
           ), '[]'::jsonb) || case when random() < 0.005 then '["Elixir"]'::jsonb else '[]'::jsonb end,
           'total_experience_years', round((random() * 20)::numeric, 1)
       )
from candidates c join users u on u.id = c.user_id where u.email like 'bench-%@example.com';
analyze resumes;
SQL
seeded="$(echo "select count(*) from resumes where file_url = 'bench://resume'" | sql)"
total="$(echo "select count(*) from resumes" | sql)"
[[ "$seeded" == "$RESUMES" ]] && pass "${seeded} رزومه در $((SECONDS - started)) ثانیه ساخته شد (کل جدول: ${total})" || { fail "ساخت داده: ${seeded}"; exit 1; }

explain() {  # <شرط WHERE> → «زمان اجرا (ms)|نوع اسکن|تعداد نتیجه»
    printf '%s\n' "set max_parallel_workers_per_gather = 0;" \
        "explain (analyze, buffers, format json) select count(*) from resumes where $1;" | sql \
        | python_json
}
python_json() {
    "$PYTHON" -c '
import json, sys
plan = json.loads(sys.stdin.read())[0]
def walk(node):
    yield node
    for child in node.get("Plans", []):
        yield from walk(child)
nodes = list(walk(plan["Plan"]))
# اسکن با ایندکس (مثلاً Bitmap Index Scan زیر Bitmap Heap Scan) مقدم بر بقیه — همان چیزی که نشان می‌دهد ایندکس استفاده شده
indexed = [n["Node Type"] + " on " + n["Index Name"] for n in nodes if "Index Name" in n]
scans = indexed or [n["Node Type"] for n in nodes if "Scan" in n["Node Type"]]
rows = nodes[1].get("Actual Rows", 0) if len(nodes) > 1 else 0
execution_ms = plan["Execution Time"]
scan = scans[0] if scans else "-"
print(f"{execution_ms:.1f}|{scan}|{rows}")'
}
PYTHON=""
for candidate in python3 python; do
    if "$candidate" -c "import json" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
[[ -n "$PYTHON" ]] || { echo "Python روی این سیستم پیدا نشد" >&2; exit 2; }

compare() {  # <عنوان> <شرط قبلی> <شرط جدید> <نام ایندکس مورد انتظار>
    local old new old_ms old_scan old_rows new_ms new_scan new_rows
    old="$(explain "$2")"; new="$(explain "$3")"
    IFS='|' read -r old_ms old_scan old_rows <<<"$old"
    IFS='|' read -r new_ms new_scan new_rows <<<"$new"
    info "$1"
    info "  قبلی:  ${old_ms} ms · ${old_scan} · ${old_rows} نتیجه"
    info "  جدید:  ${new_ms} ms · ${new_scan} · ${new_rows} نتیجه"
    if [[ "$new_scan" == *"$4"* && "$old_rows" == "$new_rows" ]]; then
        pass "$1: ایندکس ${4} استفاده شد، نتیجه‌ها یکسان، $("$PYTHON" -c "print(round(float('$old_ms') / max(float('$new_ms'), 0.01)))" ) برابر سریع‌تر"
    else
        fail "$1: ${new_scan} (انتظار ${4})، نتیجه‌ها ${old_rows} / ${new_rows}"
    fi
}

# =============================================================================
section "مقایسه‌ی کوئری قبلی و جدید (EXPLAIN ANALYZE، بدون اجرای موازی)"
# =============================================================================
compare "مهارت نادر «Elixir»" \
    "exists (select 1 from jsonb_array_elements_text(coalesce(skill_analysis -> 'skills', '[]'::jsonb)) as e where lower(e) = lower('Elixir'))" \
    "ats_resume_skill_keys(skill_analysis) @> array[lower('Elixir')]" \
    "ix_resumes_skill_keys_gin"
compare "دو مهارت هم‌زمان «kubernetes» و «terraform» (بدون حساسیت به حروف)" \
    "exists (select 1 from jsonb_array_elements_text(coalesce(skill_analysis -> 'skills', '[]'::jsonb)) as e where lower(e) = 'kubernetes') and exists (select 1 from jsonb_array_elements_text(coalesce(skill_analysis -> 'skills', '[]'::jsonb)) as e where lower(e) = 'terraform')" \
    "ats_resume_skill_keys(skill_analysis) @> array[lower('kubernetes'), lower('terraform')]" \
    "ix_resumes_skill_keys_gin"
compare "سابقه‌ی حداقل ۱۹٫۵ سال" \
    "cast(skill_analysis ->> 'total_experience_years' as double precision) >= 19.5" \
    "ats_resume_experience_years(skill_analysis) >= 19.5" \
    "ix_resumes_experience_years"

# =============================================================================
section "زمان پاسخ واقعی API جستجو (۱۰ درخواست، از داخل Pod بک‌اند)"
# =============================================================================
api="$(k exec -i deploy/backend-api -c backend-api -- python - <<'PY' 2>&1
import asyncio, statistics, time
import httpx
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.models import User


async def main() -> None:
    async with AsyncSessionLocal() as session:
        hr = User(email=f"bench-hr-{int(time.time())}@example.com", password_hash="!", role="HR_Manager")
        session.add(hr)
        await session.commit()
        token, _ = create_access_token(str(hr.id))
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=60) as client:
        for params, label in (({"skills": ["Elixir"]}, "skills=Elixir"),
                              ({"skills": ["kubernetes", "terraform"], "min_experience_years": 15}, "skills=kubernetes,terraform&min_experience_years=15")):
            timings = []
            for _ in range(10):
                started = time.monotonic()
                response = await client.get("/api/v1/candidates/search/", params=params, headers=headers)
                timings.append((time.monotonic() - started) * 1000)
                assert response.status_code == 200, response.text
            print(f"API {label} | {len(response.json()['items'])} نتیجه در صفحه‌ی اول | میانه {statistics.median(timings):.0f}ms | بیشینه {max(timings):.0f}ms")


asyncio.run(main())
PY
)"
grep "^API" <<<"$api" | sed 's/^API /          /' | tee -a "$REPORT"
grep -q "^API" <<<"$api" && pass "API جستجوی کارجویان روی ${total} رزومه پاسخ داد" || fail "API جستجو: ${api}"

# =============================================================================
section "پاک‌سازی"
# =============================================================================
if [[ "${KEEP_DATA:-0}" != "1" ]]; then
    sql <<'SQL'
delete from resumes where file_url = 'bench://resume';
delete from candidates where user_id in (select id from users where email like 'bench-%@example.com');
delete from users where email like 'bench-%@example.com';
analyze resumes;
SQL
    info "رزومه‌ها و کاربران آزمایشی حذف شدند (KEEP_DATA=1 برای نگه‌داشتن)"
fi
info "گزارش کامل: ${REPORT}"

printf '\n\033[1m━━━ نتیجه: %d PASS · %d FAIL ━━━\033[0m\n' "$PASSED" "$FAILED" | tee -a "$REPORT"
((FAILED == 0)) && { printf '\033[1;32m[GIN INDEX PASS]\033[0m\n' | tee -a "$REPORT"; exit 0; }
printf '\033[1;31m[GIN INDEX FAIL]\033[0m\n' | tee -a "$REPORT"
exit 1
