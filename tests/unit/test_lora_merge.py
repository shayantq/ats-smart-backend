"""برابری ادغام لایه‌ای با merge رسمی مدل کوچک؛ بدون دریافت وزن واقعی."""

import json

import pytest

from training.lora import merge as merger


def test_streamed_merge_matches_peft_and_preserves_source(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    peft = pytest.importorskip("peft")
    safe = pytest.importorskip("safetensors.torch")
    torch.manual_seed(42)
    base, adapter, output = (tmp_path / name for name in ("base", "adapter", "output"))
    base.mkdir()
    adapter.mkdir()
    model = torch.nn.Module()
    model.proj = torch.nn.Linear(8, 8, bias=False)
    original = model.proj.weight.detach().clone()
    safe.save_file({"proj.weight": original}, base / "weights.safetensors")
    (base / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"proj.weight": "weights.safetensors"}})
    )
    (base / "download_manifest.json").write_text(
        json.dumps(
            {
                "revision": merger.REVISION,
                "verified": True,
                "sha256": {"weights.safetensors": merger.sha256(base / "weights.safetensors")},
            }
        )
    )
    for name in (
        "config.json",
        "generation_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
    ):
        (base / name).write_text("{}")
    tuned = peft.get_peft_model(model, peft.LoraConfig(r=16, lora_alpha=32, target_modules=["proj"], bias="none"))
    with torch.no_grad():
        tuned.base_model.model.proj.lora_B.default.weight.normal_()
    state = peft.get_peft_model_state_dict(tuned)
    torch.save(state, adapter / "adapter_model.bin")
    (adapter / "adapter_config.json").write_text(json.dumps({"r": 16, "lora_alpha": 32, "bias": "none"}))
    monkeypatch.setattr(merger, "windows_memory", lambda: None)
    merger.merge(base, adapter, output)
    expected = tuned.merge_and_unload(safe_merge=True).proj.weight
    actual = safe.load_file(output / "model-00001-of-00001.safetensors")["proj.weight"]
    assert torch.equal(expected, actual)
    assert torch.equal(safe.load_file(base / "weights.safetensors")["proj.weight"], original)
    with pytest.raises(FileExistsError):
        merger.merge(base, adapter, output)
