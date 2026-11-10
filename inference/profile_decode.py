"""پروفایل محدود تولید واقعی؛ گزارش عددی است و متن ورودی/خروجی ذخیره نمی‌شود."""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx
from tokenizers import Tokenizer
from pydantic import ValidationError

from app.model_inference.contract import GeneratedAnalysis, chat_prompt
from inference.benchmark import validation_requests


async def run(args):
    if args.report.exists():
        raise FileExistsError("گزارش قبلی حفظ می‌شود")
    rows = []
    tokenizer = Tokenizer.from_file("models/base-model/tokenizer.json")
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11435", trust_env=False, timeout=90) as http:
        async with asyncio.timeout(180):
            while True:
                try:
                    if (await http.get("/health")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
        for repetition, phase in enumerate(("first", *(["warm"] * args.repeats))):
            for index, request, label in validation_requests(4):
                prompt = chat_prompt(request)
                started = time.perf_counter()
                payload = {
                    "prompt": prompt,
                    "stream": False,
                    "cache_prompt": False,
                    "n_predict": 640,
                    "temperature": 0,
                    "seed": 2026,
                    "top_k": 0,
                    "top_p": 1.0,
                    "repeat_penalty": 1.0,
                    "json_schema": GeneratedAnalysis.model_json_schema(),
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                }
                if args.compact:
                    payload.pop("json_schema")
                    payload["grammar"] = json.loads(args.grammar_file.read_text(encoding="utf-8"))["grammar"]
                elif args.constraint == "json":
                    payload["json_schema"] = {"type": "object"}
                elif args.constraint == "none":
                    payload.pop("json_schema")
                response = await http.post("/completion", json=payload)
                seconds = time.perf_counter() - started
                response.raise_for_status()
                result = response.json()
                try:
                    output = GeneratedAnalysis.model_validate_json(result["content"])
                except ValidationError:
                    output = None
                row = {
                    "phase": phase,
                    "repetition": repetition,
                    "index": index,
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "seconds": seconds,
                    "valid": output is not None
                    and result.get("stop_type") in ("eos", "word")
                    and not result.get("truncated", False),
                    "score": output.score if output is not None else None,
                    "output_sha256": hashlib.sha256(result["content"].encode()).hexdigest(),
                    "label": label,
                    "timings": result.get("timings"),
                    "compact_tokens": (
                        len(
                            tokenizer.encode(
                                json.dumps(json.loads(result["content"]), ensure_ascii=False, separators=(",", ":")),
                                add_special_tokens=False,
                            ).ids
                        )
                        if output is not None
                        else None
                    ),
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(
                    json.dumps(
                        {
                            "synthetic_validation": True,
                            "configuration": args.name,
                            "constraint": args.constraint,
                            "rows": rows,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--repeats", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--grammar-file", type=Path, default=Path("models/compact_grammar.json"))
    parser.add_argument("--constraint", choices=["schema", "json", "none"], default="schema")
    asyncio.run(run(parser.parse_args()))
