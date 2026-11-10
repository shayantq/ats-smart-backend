"""صدور grammar ترکیبی با مبدل رسمی ثابت؛ محدودیت محتوای پاسخ تغییر نمی‌کند."""

import hashlib
import argparse
import importlib.util
import json
from pathlib import Path

from app.model_inference.contract import GeneratedAnalysis

CONVERTER_SHA256 = "280962de54225612e32e265b5889da57243ab373885524e521f7f71350f4c77f"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--converter", type=Path, default=Path("models/json_schema_to_grammar_b4514.py"))
    parser.add_argument("--output", type=Path, default=Path("models/hybrid-verified.json"))
    args = parser.parse_args()
    source, output = args.converter, args.output
    if output.exists():
        raise FileExistsError("grammar قبلی حفظ می‌شود")
    if hashlib.sha256(source.read_bytes()).hexdigest() != CONVERTER_SHA256:
        raise ValueError("هش مبدل رسمی تغییر کرده است")
    spec = importlib.util.spec_from_file_location("official_schema_converter", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SPACE_RULE = '""'
    schema = GeneratedAnalysis.model_json_schema()
    # resolve_refs شیء schema را درجا تغییر می‌دهد؛ اثر انگشت باید پیش از آن گرفته شود.
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    converter = module.SchemaConverter(prop_order={}, allow_fetch=False, dotall=False, raw_pattern=False)
    converter.visit(converter.resolve_refs(schema, "https://ats.invalid/schema.json"), "")
    lines = []
    for line in converter.format_grammar().splitlines():
        if line.startswith("root ::="):
            line = line.replace(" space ", " prefix-space ", 1)
        elif line.startswith("score-kv ::="):
            line = line.replace(" space ", " prefix-space ")
        lines.append(line)
    lines.append(r'prefix-space ::= | " " | "\n" [ \t]{0,20}')
    report = {
        "grammar": "\n".join(lines),
        "schema_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "converter_sha256": CONVERTER_SHA256,
        "format": "score-prefix preserved; decorative whitespace removed",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifact": str(output), "schema_sha256": report["schema_sha256"]}))


if __name__ == "__main__":
    main()
