"""
قراردادهای ماشین‌خوان سرویس هوش مصنوعی مولد — منبع حقیقت، خودِ کد است:

    docs/genai/interview-question-set.schema.json   JSON Schema خروجی مدل زبانی (از GeneratedQuestionSet)
    docs/genai/openapi.json                          OpenAPI مسیرهای /api/v1/genai (از خودِ FastAPI)

بعد از هر تغییر اسکیماها یا مسیرها:   python -m app.genai.contract
تست واحد tests/unit/test_genai_contract.py تفاوت فایل‌های داخل ریپو با خروجی فعلی کد را رد می‌کند.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.schemas.genai import GeneratedQuestionSet

LLM_SCHEMA_NAME = "interview_question_set"
DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "genai"
SCHEMA_PATH = DOCS_DIR / "interview-question-set.schema.json"
OPENAPI_PATH = DOCS_DIR / "openapi.json"
GENAI_PATH_PREFIX = "/api/v1/genai"


def llm_output_json_schema(question_count: int | None = None) -> dict:
    """
    JSON Schema خروجی مدل — بدون تعریف‌های تودرتو ($defs/$ref، که بعضی سرویس‌ها در خروجی مقید
    نمی‌پذیرند)، همه‌ی فیلدها اجباری و بدون فیلد اضافه (additionalProperties: false).

    question_count: در درخواست واقعی، تعداد آیتم‌های questions دقیقاً برابر نقشه‌ی سؤال‌ها قفل می‌شود
    (minItems = maxItems) — مدل نمی‌تواند کمتر یا بیشتر برگرداند. بدون آن (فایل docs): بازه‌ی ۱ تا ۱۵.
    """
    schema = GeneratedQuestionSet.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(copy.deepcopy(definitions[node["$ref"].split("/")[-1]]))
            return {key: inline(value) for key, value in node.items()}
        if isinstance(node, list):
            return [inline(item) for item in node]
        return node

    result = inline(schema)
    if question_count is not None:
        result["properties"]["questions"]["minItems"] = question_count
        result["properties"]["questions"]["maxItems"] = question_count
    return result


def openapi_contract() -> dict:
    """زیرمجموعه‌ی OpenAPI برنامه: فقط مسیرهای GenAI و اسکیماهایی که به آن‌ها ارجاع می‌دهند."""
    from app.main import app

    full = app.openapi()
    paths = {path: item for path, item in full["paths"].items() if path.startswith(GENAI_PATH_PREFIX)}
    components = full.get("components", {}).get("schemas", {})
    needed: set[str] = set()

    def collect(node) -> None:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
                name = reference.split("/")[-1]
                if name not in needed:
                    needed.add(name)
                    collect(components.get(name, {}))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(paths)
    contract = {
        "openapi": full["openapi"],
        "info": {
            "title": "ATS Smart — GenAI Interview Questions API",
            "version": "1.0.0",
            "description": "قرارداد API تولید و بازبینی بانک سؤال مصاحبه — راهنمای کامل: docs/genai/API_CONTRACT.md",
        },
        "paths": paths,
        "components": {"schemas": {name: components[name] for name in sorted(needed)}},
    }
    security = full.get("components", {}).get("securitySchemes")
    if security:
        contract["components"]["securitySchemes"] = security
    return contract


def render(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(render(llm_output_json_schema()), encoding="utf-8")
    OPENAPI_PATH.write_text(render(openapi_contract()), encoding="utf-8")
    print(f"written: {SCHEMA_PATH.relative_to(DOCS_DIR.parents[1])}")
    print(f"written: {OPENAPI_PATH.relative_to(DOCS_DIR.parents[1])}")


if __name__ == "__main__":
    main()
