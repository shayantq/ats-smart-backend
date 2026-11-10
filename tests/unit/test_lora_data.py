"""
تست‌های آماده‌سازی داده‌ی LoRA (training/lora/data.py): رندر با قالب چت، ماسک loss فقط روی پاسخ،
فیلتر طول (بدون بریدن بی‌صدا)، زیرمجموعه‌ی ثابت validation و هم‌طول‌سازی دسته.

به transformers/torch نیاز دارد؛ در CI (بدون requirements-train.txt) خودکار رد می‌شود.
"""

import json

import pytest

transformers = pytest.importorskip("transformers")

from tokenizers import Tokenizer  # noqa: E402

from training.lora.data import (  # noqa: E402
    IGNORE_INDEX,
    PadCollator,
    encode_record,
    encode_split,
    prompt_ids,
    record_score,
    stratified_subset,
)
from tests.finetune_helpers import build_test_tokenizer  # noqa: E402

CHATML = (
    "{% for message in messages %}<|im_start|>{{ message['role'] }}\n{{ message['content'] }}<|im_end|>\n"
    "{% endfor %}{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}"
)


@pytest.fixture(scope="module")
def tokenizer(tmp_path_factory):
    path = build_test_tokenizer(tmp_path_factory.mktemp("tok"))
    return transformers.PreTrainedTokenizerFast(
        tokenizer_object=Tokenizer.from_file(path),
        chat_template=CHATML,
        eos_token="<|im_end|>",
        pad_token="<|im_end|>",
    )


def _record(score: int = 70, extra: str = "") -> dict:
    output = json.dumps({"score": score, "verdict": "مناسب"}, ensure_ascii=False)
    return {"instruction": "ارزیابی کن", "input": "## آگهی شغلی\nPython" + extra, "output": output}


def test_loss_is_only_on_assistant_tokens(tokenizer):
    record = _record()
    encoded = encode_record(tokenizer, record, 4096)
    prompt = prompt_ids(tokenizer, record)
    labels, ids = encoded["labels"], encoded["input_ids"]
    assert len(labels) == len(ids)
    assert labels[: len(prompt)] == [IGNORE_INDEX] * len(prompt)
    assert labels[len(prompt) :] == ids[len(prompt) :]
    answer = tokenizer.decode([token for token in labels if token != IGNORE_INDEX])
    assert answer.startswith(record["output"]) and "<|im_end|>" in answer
    assert "ارزیابی کن" not in answer and "آگهی" not in answer


def test_prompt_ends_with_the_assistant_header(tokenizer):
    text = tokenizer.decode(prompt_ids(tokenizer, _record()))
    assert text.startswith("<|im_start|>system\nارزیابی کن<|im_end|>\n<|im_start|>user\n")
    assert text.endswith("<|im_start|>assistant\n")


def test_long_records_are_dropped_and_counted_not_truncated(tokenizer):
    short, long = _record(), _record(extra=" توضیح" * 400)
    limit = len(encode_record(tokenizer, short, 100_000)["input_ids"]) + 5
    assert encode_record(tokenizer, long, limit) is None
    split = encode_split(tokenizer, [short, long, short], limit)
    assert split.dropped_too_long == 1
    assert len(split.examples) == 2
    assert all(len(example["input_ids"]) <= limit for example in split.examples)


def test_mismatched_chat_template_is_rejected(tokenizer):
    # قالبی که نشانه‌ی شروع پاسخ را فقط در حالت تولید می‌گذارد: پیشوند پرامپت با گفت‌وگوی کامل جور نیست
    template = "{% for m in messages %}{{ m['content'] }}{% endfor %}{% if add_generation_prompt %}>>{% endif %}"
    broken = transformers.PreTrainedTokenizerFast(tokenizer_object=tokenizer.backend_tokenizer, chat_template=template)
    with pytest.raises(ValueError):
        encode_record(broken, _record(), 4096)


def test_stratified_subset_is_deterministic_and_keeps_score_distribution():
    records = [_record(score=score % 101) for score in range(1000)]
    first = stratified_subset(records, 300, seed=42)
    assert first == stratified_subset(records, 300, seed=42)
    assert first != stratified_subset(records, 300, seed=7)
    assert len(first) == 300
    for bucket in range(5):
        share_all = sum(1 for r in records if min(record_score(r) // 20, 4) == bucket) / len(records)
        share_subset = sum(1 for r in first if min(record_score(r) // 20, 4) == bucket) / len(first)
        assert abs(share_all - share_subset) < 0.01
    assert stratified_subset(records[:10], 300, seed=1) == records[:10]


def test_collator_pads_inputs_labels_and_mask():
    torch = pytest.importorskip("torch")
    batch = PadCollator(pad_token_id=0)(
        [{"input_ids": [5, 6, 7], "labels": [-100, 6, 7]}, {"input_ids": [8], "labels": [8]}]
    )
    assert batch["input_ids"].tolist() == [[5, 6, 7], [8, 0, 0]]
    assert batch["labels"].tolist() == [[-100, 6, 7], [8, -100, -100]]
    assert batch["attention_mask"].tolist() == [[1, 1, 1], [1, 0, 0]]
    assert batch["input_ids"].dtype == torch.long
