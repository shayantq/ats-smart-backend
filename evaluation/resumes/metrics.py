"""محاسبهٔ قطعی؛ مقادیر رزومه هرگز وارد گزارش نمی‌شوند."""

import math
import unicodedata
from collections import Counter


def norm(value):
    if not isinstance(value, str):
        return value
    return " ".join(
        unicodedata.normalize("NFKC", value)
        .translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يك", "01234567890123456789یک"))
        .replace("\u200c", " ")
        .split()
    ).casefold()


def equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= 1 / 365.2425
    return norm(a) == norm(b)


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return dict(tp=tp, fp=fp, fn=fn, precision=p, recall=r, f1=f)


def signature(record):
    return (record.kind, tuple(sorted((k, str(norm(v))) for k, v in record.fields.items() if v is not None)))


def score(expected, predicted):
    # اتصال یک‌به‌یک با بیشترین تطابق فیلد؛ تساوی‌ها با ترتیب ثابت شکسته می‌شوند.
    pairs = []
    for i, a in enumerate(expected):
        for j, b in enumerate(predicted):
            if a.kind == b.kind:
                count = sum(v is not None and equal(v, b.fields.get(k)) for k, v in a.fields.items())
                if count:
                    pairs.append((-count, i, j))
    matches, left, right = [], set(), set()
    for _, i, j in sorted(pairs):
        if i not in left and j not in right:
            matches.append((expected[i], predicted[j]))
            left.add(i)
            right.add(j)
    tp = fp = fn = exact = abstained = unknown = certainty = linked = links = 0
    by_field = {}
    date_ok = date_n = evidence_n = 0

    def add(key, t=0, p=0, n=0):
        row = by_field.setdefault(key, [0, 0, 0])
        row[0] += t
        row[1] += p
        row[2] += n

    for a, b in matches:
        full = True
        for key in a.fields.keys() | b.fields.keys():
            av, bv = a.fields.get(key), b.fields.get(key)
            label = a.kind + "." + key
            if key in a.fields and av is None:
                unknown += 1
                if bv is None:
                    abstained += 1
                else:
                    certainty += 1
                    fp += 1
                    add(label, p=1)
                    full = False
            elif av is not None and equal(av, bv):
                tp += 1
                add(label, t=1)
            else:
                fn += av is not None
                fp += bv is not None
                add(label, n=int(av is not None), p=int(bv is not None))
                full = False
            if key in {"duration", "years", "is_valid"} and av is not None:
                date_n += 1
                date_ok += equal(av, bv)
        exact += full
        if a.kind == "employment":
            links += 1
            linked += all(equal(a.fields.get(k), b.fields.get(k)) for k in ("company", "job_title", "duration"))
        # شاهد باید بخشی از شاهد مرجع باشد؛ رشتهٔ دلخواه به‌عنوان شاهد پذیرفته نیست.
        evidence_n += any(norm(e) in norm("\n".join(a.evidence)) for e in b.evidence if e.strip())
    for i, a in enumerate(expected):
        if i not in left:
            for k, v in a.fields.items():
                if v is not None:
                    fn += 1
                    add(a.kind + "." + k, n=1)
                else:
                    unknown += 1
                    abstained += 1
            if a.kind == "employment":
                links += 1
            date_n += sum(k in {"duration", "years", "is_valid"} and v is not None for k, v in a.fields.items())
    for j, b in enumerate(predicted):
        if j not in right:
            for k, v in b.fields.items():
                if v is not None:
                    fp += 1
                    add(b.kind + "." + k, p=1)
    counts = Counter(signature(x) for x in predicted)
    return dict(
        fields=prf(tp, fp, fn),
        records=prf(exact, len(predicted) - exact, len(expected) - exact),
        omissions=len(expected) - len(left),
        unsupported_records=len(predicted) - exact,
        unmatched_predictions=len(predicted) - len(right),
        incorrect_linkage=links - linked,
        linkage=dict(correct=linked, denominator=links),
        duplicates=sum(n - 1 for n in counts.values()),
        dates=dict(correct=date_ok, denominator=date_n),
        evidence=dict(covered=evidence_n, denominator=len(expected)),
        unknown=dict(abstained=abstained, denominator=unknown, inappropriate_certainty=certainty),
        per_field={k: prf(*v) for k, v in sorted(by_field.items())},
    )
