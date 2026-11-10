"""آزمون سلامت داده، محافظت از اجرا و رفت‌وبرگشت واقعی آداپتر روی یک مدل کوچک CPU."""

import copy
import json
from dataclasses import replace

import pytest

from training.lora.config import LoraSettings, RunConfig
from training.lora.data import audited_records
from training.lora.train import apply_lora, build_config, parse_args, prepare_run, validate_trainable_parameters


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    manifest, stats = {"splits": {}}, {"splits": {}}
    for name in ("train", "validation", "test"):
        record = {"instruction": "ارزیابی", "input": f"رزومه‌ی {name}", "output": '{"score":70}'}
        (root / f"{name}.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest["splits"][name] = [{"group": name, "pii": []}]
        stats["splits"][name] = {"records": 1}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    return root


def test_dataset_audit_checks_the_actual_split_counts(dataset):
    _, report = audited_records(dataset)
    assert report["split_isolation_passed"]
    (dataset / "test.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="شمارش"):
        audited_records(dataset)


def test_candidate_leakage_is_rejected(dataset):
    path = dataset / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["splits"]["test"][0]["group"] = "train"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="نشت"):
        audited_records(dataset)


def test_same_input_in_two_splits_is_rejected_even_with_different_scores(dataset):
    record = json.loads((dataset / "train.jsonl").read_text(encoding="utf-8"))
    record["output"] = '{"score":20}'
    (dataset / "test.jsonl").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="نشت"):
        audited_records(dataset)


def test_resume_requires_a_checkpoint_and_unchanged_dataset(dataset, tmp_path):
    config = RunConfig(base_model="local", data_dir=dataset, output_root=tmp_path / "outputs")
    config = replace(config, runs_root=tmp_path / "logs", reports_root=tmp_path / "reports")
    assert prepare_run(config, resume=False) is None
    with pytest.raises(ValueError, match="قبلاً"):
        prepare_run(config, resume=False)
    with pytest.raises(ValueError, match="checkpoint"):
        prepare_run(config, resume=True)
    (config.output_dir / "checkpoints" / "checkpoint-10").mkdir(parents=True)
    assert prepare_run(config, resume=True).endswith("checkpoint-10")
    with (dataset / "train.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="دیتاست"):
        prepare_run(config, resume=True)


@pytest.mark.parametrize("stage", ["failed", "paused_by_user"])
def test_stopped_workflow_can_resume_without_discarding_evidence(dataset, tmp_path, stage):
    from training.lora import workflow

    config = RunConfig(
        base_model="local",
        data_dir=dataset,
        output_root=tmp_path / "outputs",
        runs_root=tmp_path / "runs",
        reports_root=tmp_path / "reports",
    )
    prepare_run(config, resume=False)
    checkpoint = config.output_dir / "checkpoints/checkpoint-50"
    checkpoint.mkdir(parents=True)
    (checkpoint / "trainer_state.json").write_text(json.dumps({"global_step": 50}), encoding="utf-8")
    for name in ("adapter_model.safetensors", "optimizer.pt", "scheduler.pt", "rng_state.pth"):
        (checkpoint / name).write_bytes(b"checkpoint-fixture")
    directory = tmp_path / "workflow"
    directory.mkdir()
    previous = {"stage": stage, "updated_at": "2026-11-09T00:00:00+00:00"}
    status = directory / "status.json"
    status.write_text(json.dumps(previous), encoding="utf-8")
    (directory / "process.json").write_text(json.dumps({"started_at": "2026-11-08T20:00:00+00:00"}))
    if stage == "paused_by_user":
        workflow.append_attempt(directory, "training_paused_by_user", 7200, 0)
    expected_hours = 2 if stage == "paused_by_user" else 4
    assert workflow.prepare_failed_resume(directory, config) == 50
    assert json.loads(status.read_text()) == previous
    archived = list(directory.glob("status-before-resume-*.json"))
    assert len(archived) == 1 and json.loads(archived[0].read_text()) == previous
    assert workflow.processing_hours(directory) == expected_hours
    (checkpoint / "optimizer.pt").write_bytes(b"")
    with pytest.raises(ValueError, match="کامل نیست"):
        workflow.prepare_failed_resume(directory, config)
    assert workflow.processing_hours(directory) == expected_hours


def test_paused_resume_requires_active_time_ledger_before_archiving(tmp_path):
    from training.lora import workflow

    (tmp_path / "status.json").write_text(json.dumps({"stage": "paused_by_user"}), encoding="utf-8")
    with pytest.raises(ValueError, match="سابقهٔ زمان فعال"):
        workflow.prepare_failed_resume(tmp_path, RunConfig(base_model="local"))
    assert not list(tmp_path.glob("status-before-resume-*"))


def test_finalization_uses_best_checkpoint_and_preserves_original_training_plan(dataset, tmp_path):
    from training.lora.finalize import finalization_checkpoint

    config = RunConfig(
        base_model="local",
        data_dir=dataset,
        output_root=tmp_path / "outputs",
        runs_root=tmp_path / "runs",
        reports_root=tmp_path / "reports",
    )
    prepare_run(config, resume=False)
    best = config.output_dir / "checkpoints/checkpoint-50"
    latest = config.output_dir / "checkpoints/checkpoint-100"
    state = {"global_step": 100, "max_steps": 1032, "best_model_checkpoint": str(best), "best_metric": 0.1}
    for checkpoint, step in ((best, 50), (latest, 100)):
        checkpoint.mkdir(parents=True)
        (checkpoint / "trainer_state.json").write_text(json.dumps({**state, "global_step": step}), encoding="utf-8")
        (checkpoint / "adapter_config.json").write_text("{}", encoding="utf-8")
        (checkpoint / "adapter_model.safetensors").write_bytes(b"checkpoint-fixture")
    original_manifest = (config.output_dir / "run_manifest.json").read_bytes()
    original_state = (latest / "trainer_state.json").read_bytes()
    selected, restored = finalization_checkpoint(config)
    assert selected == best and restored["global_step"] == 100 and restored["max_steps"] == 1032
    assert (config.output_dir / "run_manifest.json").read_bytes() == original_manifest
    assert (latest / "trainer_state.json").read_bytes() == original_state
    (best / "adapter_model.safetensors").write_bytes(b"")
    with pytest.raises(ValueError, match="کامل نیستند"):
        finalization_checkpoint(config)
    (best / "adapter_model.safetensors").write_bytes(b"checkpoint-fixture")
    state["best_model_checkpoint"] = str(tmp_path / "other-run/checkpoint-50")
    (latest / "trainer_state.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="داخل همین اجرا"):
        finalization_checkpoint(config)
    (config.output_dir / "adapter").mkdir()
    with pytest.raises(ValueError, match="بازنویسی"):
        finalization_checkpoint(config)


@pytest.mark.parametrize("limit", [100, 200])
def test_finalization_workflow_never_invokes_training_and_keeps_requested_test_count(tmp_path, monkeypatch, limit):
    from training.lora import finalize

    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "training/reports/test-workflow"
    directory.mkdir(parents=True)
    previous = {"stage": "stopped_by_user_for_final_evaluation"}
    (directory / "status.json").write_text(json.dumps(previous), encoding="utf-8")
    monkeypatch.setattr(finalize, "resolve_base_model", lambda _: "local")
    monkeypatch.setattr(finalize, "finalization_checkpoint", lambda _: (tmp_path / "checkpoint-900", {}))
    stages = []
    monkeypatch.setattr(
        finalize, "run_command", lambda directory, stage, module, *args: stages.append((stage, module, args))
    )
    evaluated = []
    monkeypatch.setattr(finalize, "complete_evaluation", lambda *args: evaluated.append(args) or 0)
    assert finalize.main(["--run-id", "test", "--evaluation-limit", str(limit), "--evaluation-batch-size", "4"]) == 0
    assert len(stages) == 1 and stages[0][1] == "training.lora.finalize" and "--export-only" in stages[0][2]
    assert evaluated[0][-2:] == (4, limit)
    assert json.loads((directory / "status.json").read_text()) == previous
    assert len(list(directory.glob("status-before-finalize-*"))) == 1


def test_finalization_retry_is_bounded_and_requires_archived_user_request(tmp_path):
    from training.lora.finalize import authorized_finalization
    from training.lora.workflow import append_attempt

    failed = {"stage": "failed"}
    append_attempt(tmp_path, "final_validation_and_export", 10, 1)
    assert not authorized_finalization(tmp_path, failed)
    (tmp_path / "status-before-finalize-test.json").write_text(
        json.dumps({"stage": "stopped_by_user_for_final_evaluation"}), encoding="utf-8"
    )
    assert authorized_finalization(tmp_path, failed)
    assert not authorized_finalization(tmp_path, {"stage": "training"})
    append_attempt(tmp_path, "final_validation_and_export", 10, 1)
    assert not authorized_finalization(tmp_path, failed)


def test_real_finalization_evaluates_frozen_adapter_without_training(dataset, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from training.lora import finalize, train

    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")
    pytest.importorskip("peft")
    config = RunConfig(
        base_model="local",
        data_dir=dataset,
        output_root=tmp_path / "outputs",
        runs_root=tmp_path / "runs",
        reports_root=tmp_path / "reports",
    )
    prepare_run(config, resume=False)
    checkpoint = config.output_dir / "checkpoints/checkpoint-50"
    base = transformers.LlamaForCausalLM(
        transformers.LlamaConfig(
            vocab_size=32,
            hidden_size=16,
            intermediate_size=32,
            num_hidden_layers=1,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=32,
        )
    )
    adapter = apply_lora(copy.deepcopy(base), LoraSettings())
    adapter.save_pretrained(checkpoint, save_embedding_layers=False)
    transformers.TrainerState(
        global_step=50,
        max_steps=1032,
        epoch=0.1,
        best_model_checkpoint=str(checkpoint),
        best_metric=0.1,
        log_history=[{"step": 50, "loss": 0.2}, {"step": 50, "eval_loss": 0.1}],
    ).save_to_json(str(checkpoint / "trainer_state.json"))
    original_manifest = (config.output_dir / "run_manifest.json").read_bytes()
    original_state = (checkpoint / "trainer_state.json").read_bytes()
    tokenizer = transformers.PreTrainedTokenizerFast(
        tokenizer_object=tokenizers.Tokenizer(tokenizers.models.WordLevel({"[PAD]": 0, "[UNK]": 1}, unk_token="[UNK]")),
        pad_token="[PAD]",
        unk_token="[UNK]",
    )
    feature = {"input_ids": [1, 2, 3, 4], "labels": [-100, -100, 3, 4]}
    monkeypatch.setattr(train, "load_tokenizer", lambda _: tokenizer)
    monkeypatch.setattr(
        train, "load_splits", lambda *args: ({"validation_full": SimpleNamespace(examples=[feature])}, {})
    )
    monkeypatch.setattr(train, "load_model", lambda _: copy.deepcopy(base))
    monkeypatch.setattr(
        train,
        "training_arguments",
        lambda *args: transformers.TrainingArguments(
            output_dir=str(tmp_path / "eval-output"),
            use_cpu=True,
            report_to=[],
            eval_strategy="steps",
            eval_steps=50,
            prediction_loss_only=True,
            label_names=["labels"],
            remove_unused_columns=False,
            disable_tqdm=True,
        ),
    )
    monkeypatch.setattr(train, "resume_tensorboard_writer", lambda *args: None)
    monkeypatch.setattr(train, "check_resources", lambda *args, **kwargs: {})
    monkeypatch.setattr(finalize, "check_resources", lambda *args, **kwargs: {})
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "is_bf16_supported", lambda: True)
    monkeypatch.setattr(torch.cuda, "reset_peak_memory_stats", lambda: None)
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 0)
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)

    def forbidden_training(*args, **kwargs):
        pytest.fail("finalization must never invoke Trainer.train")

    monkeypatch.setattr(transformers.Trainer, "train", forbidden_training)
    summary = finalize.export_checkpoint(config)
    assert summary["global_steps"] == 50 and summary["additional_training_steps"] == 0
    assert summary["full_validation_completed"] and not summary["planned_training_completed"]
    assert summary["selected_checkpoint_step"] == 50 and summary["planned_optimizer_steps"] == 1032
    assert "validation_full_loss" in summary["validation_full"]
    assert (config.output_dir / "adapter/adapter_model.bin").stat().st_size > 0
    assert (config.output_dir / "run_manifest.json").read_bytes() == original_manifest
    assert (checkpoint / "trainer_state.json").read_bytes() == original_state


@pytest.mark.parametrize("stage", ["training", "completed", "acceptance_failed"])
def test_resume_refuses_active_or_finished_workflow_before_touching_state(tmp_path, stage):
    from training.lora import workflow

    status = tmp_path / "status.json"
    status.write_text(json.dumps({"stage": stage}), encoding="utf-8")
    with pytest.raises(ValueError, match="شکست"):
        workflow.prepare_failed_resume(tmp_path, RunConfig(base_model="local"))
    assert json.loads(status.read_text())["stage"] == stage
    assert not list(tmp_path.glob("status-before-resume-*"))


def test_resumed_tensorboard_hides_only_abandoned_steps(tmp_path):
    from types import SimpleNamespace
    from training.lora.train import resume_tensorboard_writer

    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("tensorboard")
    from torch.utils.tensorboard import SummaryWriter
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    from transformers.integrations import TensorBoardCallback

    logs, checkpoint = tmp_path / "logs", tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "trainer_state.json").write_text(json.dumps({"global_step": 500}), encoding="utf-8")
    with SummaryWriter(log_dir=str(logs)) as writer:
        for step in (500, 510, 530):
            writer.add_scalar("train/loss", 99, step)
    accumulator = EventAccumulator(str(logs)).Reload()
    assert [event.step for event in accumulator.Scalars("train/loss")] == [500, 510, 530]
    callback = TensorBoardCallback()
    trainer = SimpleNamespace(callback_handler=SimpleNamespace(callbacks=[callback]))
    writer = resume_tensorboard_writer(trainer, str(checkpoint), logs)
    assert callback.tb_writer is writer
    writer.add_scalar("train/loss", 0.04, 510)
    writer.close()
    accumulator.Reload()
    events = accumulator.Scalars("train/loss")
    assert [event.step for event in events] == [500, 510]
    assert events[-1].value == pytest.approx(0.04)
    # backend فعلی TensorBoard اولین START را purge نمی‌کند؛ نشانگر اولیه باید این مسیر را هم پوشش دهد.
    from tensorboard.backend.event_processing.plugin_event_accumulator import EventAccumulator as PluginAccumulator

    plugin_events = PluginAccumulator(str(logs)).Reload().Tensors("train/loss")
    assert [event.step for event in plugin_events] == [500, 510]
    assert plugin_events[-1].tensor_proto.float_val[0] == pytest.approx(0.04)


def test_smoke_is_explicitly_bounded_and_separate_from_full_training():
    config = build_config(parse_args(["--base-model", "local", "--smoke"]))
    assert config.train.smoke
    assert (config.train.max_steps, config.train.eval_steps, config.train.eval_subset) == (30, 10, 30)
    assert not build_config(parse_args(["--base-model", "local"])).train.smoke


def test_real_adapter_training_export_and_reload_leave_base_weights_frozen(tmp_path):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    peft = pytest.importorskip("peft")
    torch.manual_seed(42)
    base = transformers.LlamaForCausalLM(
        transformers.LlamaConfig(
            vocab_size=32,
            hidden_size=16,
            intermediate_size=32,
            num_hidden_layers=1,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=32,
        )
    )
    pristine = copy.deepcopy(base)
    originals = [(parameter, parameter.detach().clone()) for parameter in base.parameters()]
    model = apply_lora(base, LoraSettings())
    validate_trainable_parameters(model)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=0.01)
    ids = torch.tensor([[1, 2, 3, 4, 5, 6]])
    loss = model(input_ids=ids, labels=ids).loss
    loss.backward()
    optimizer.step()
    assert all(torch.equal(parameter.detach(), old) for parameter, old in originals)
    assert any(p.detach().abs().sum() > 0 for name, p in model.named_parameters() if "lora_B" in name)
    model.save_pretrained(tmp_path / "adapter", safe_serialization=False, save_embedding_layers=False)
    assert (tmp_path / "adapter" / "adapter_config.json").is_file()
    assert (tmp_path / "adapter" / "adapter_model.bin").stat().st_size > 0
    reloaded = peft.PeftModel.from_pretrained(pristine, tmp_path / "adapter")
    model.eval()
    reloaded.eval()
    with torch.no_grad():
        assert torch.allclose(model(input_ids=ids).logits, reloaded(input_ids=ids).logits, atol=1e-6)


@pytest.mark.parametrize("normalizer", [None, 32])
def test_answer_only_logits_preserve_loss_and_every_adapter_gradient(normalizer):
    from training.lora.data import PadCollator

    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("peft")
    torch.manual_seed(7)
    model = apply_lora(
        transformers.Qwen2ForCausalLM(
            transformers.Qwen2Config(
                vocab_size=32,
                hidden_size=16,
                intermediate_size=32,
                num_hidden_layers=1,
                num_attention_heads=4,
                num_key_value_heads=2,
                max_position_embeddings=32,
            )
        ),
        LoraSettings(dropout=0),
    )
    features = [
        {"input_ids": [1, 2, 3, 4, 5, 6], "labels": [-100, -100, -100, 4, 5, 6]},
        {"input_ids": [7, 8, 9, 10], "labels": [-100, -100, 9, 10]},
    ]
    extra = {} if normalizer is None else {"num_items_in_batch": torch.tensor(normalizer)}
    full = PadCollator(0)(features)
    selected = PadCollator(0, answer_logits_only=True)(features)
    reference_loss = model(**full, **extra).loss
    reference_loss.backward()
    gradients = {name: p.grad.clone() for name, p in model.named_parameters() if p.requires_grad}
    model.zero_grad(set_to_none=True)
    result = model(**selected, **extra)
    result.loss.backward()
    assert result.logits.shape[1] < full["input_ids"].shape[1]
    assert torch.allclose(reference_loss, result.loss, atol=1e-6)
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            assert torch.allclose(gradients[name], parameter.grad, atol=1e-6), name


@pytest.mark.parametrize("estimate", [None, 12.01, float("nan"), 0])
def test_workflow_never_starts_full_training_without_a_valid_within_budget_estimate(tmp_path, monkeypatch, estimate):
    from training.lora import workflow

    monkeypatch.chdir(tmp_path)
    stages = []

    def fake_command(directory, stage, module, *arguments):
        stages.append(stage)
        if stage == "smoke":
            report = tmp_path / "training/reports/test-smoke"
            report.mkdir(parents=True)
            (report / "run_summary.json").write_text(
                json.dumps({"timing": {"estimated_full_run_hours": estimate}}), encoding="utf-8"
            )

    monkeypatch.setattr(workflow, "run_command", fake_command)
    directory = tmp_path / "workflow"
    assert workflow.finish_training("test", directory) == 3
    assert stages == ["gpu_check", "smoke"]
    assert json.loads((directory / "status.json").read_text(encoding="utf-8"))["stage"] == "needs_training_approval"


def test_reusing_a_smoke_result_requires_unchanged_data_and_main_hyperparameters(dataset, tmp_path, monkeypatch):
    from dataclasses import asdict
    from functools import partial
    from training.lora import workflow
    from training.lora.data import dataset_fingerprint

    factory = partial(
        RunConfig,
        data_dir=dataset,
        output_root=tmp_path / "outputs",
        reports_root=tmp_path / "reports",
        runs_root=tmp_path / "logs",
    )
    monkeypatch.setattr(workflow, "RunConfig", factory)
    monkeypatch.setattr(workflow, "resolve_base_model", lambda _: "local")
    config = factory(base_model="local", run_id="prior-smoke")
    smoke = replace(config, train=replace(config.train, smoke=True, max_steps=30, eval_steps=10, eval_subset=30))
    smoke.output_dir.mkdir(parents=True)
    smoke.report_dir.mkdir(parents=True)
    manifest = {"dataset": dataset_fingerprint(dataset)}
    (smoke.output_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = {"run_kind": "smoke", "global_steps": 30, "config": asdict(smoke)}
    path = smoke.report_dir / "run_summary.json"
    path.write_text(json.dumps(report, default=str), encoding="utf-8")
    assert workflow.verified_smoke("prior-smoke")["global_steps"] == 30
    report["config"]["train"]["answer_logits_only"] = False
    path.write_text(json.dumps(report, default=str), encoding="utf-8")
    with pytest.raises(ValueError, match="هایپرپارامتر"):
        workflow.verified_smoke("prior-smoke")
    report["config"]["train"]["answer_logits_only"] = True
    path.write_text(json.dumps(report, default=str), encoding="utf-8")
    with (dataset / "test.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="دیتاست"):
        workflow.verified_smoke("prior-smoke")


def test_progress_eta_counts_only_steps_executed_after_resume(monkeypatch, capsys):
    from types import SimpleNamespace
    from training.lora import train

    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    timestamps = iter([100.0, 120.0, 160.0])
    monkeypatch.setattr(train.time, "perf_counter", lambda: next(timestamps))
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 0)
    callback = train._progress_callback(30)
    callback.on_train_begin(None, SimpleNamespace(global_step=10), None)
    callback.on_log(None, SimpleNamespace(global_step=11), None, logs={"loss": 0.12})
    log = json.loads(capsys.readouterr().out)
    assert log["step"] == 11 and log["s_per_step"] == 40.0
    assert log["eta_hours"] == round(40 * 19 / 3600, 2)


@pytest.mark.parametrize("starting,available", [(True, 7), (False, 1)])
def test_memory_guard_rejects_insufficient_commit_before_allocating(tmp_path, monkeypatch, starting, available):
    from training.lora import resources
    from types import SimpleNamespace

    monkeypatch.setattr(
        resources,
        "windows_memory",
        lambda: {
            "physical_available": 3 * resources.GIB,
            "commit_available": available * resources.GIB,
        },
    )
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda _: SimpleNamespace(free=20 * resources.GIB))
    with pytest.raises(RuntimeError, match="محافظ حافظه"):
        resources.check_resources(tmp_path, starting=starting)


def test_guard_checks_disk_even_without_windows_memory_api(tmp_path, monkeypatch):
    from training.lora import resources
    from types import SimpleNamespace

    monkeypatch.setattr(resources, "windows_memory", lambda: None)
    monkeypatch.setattr(resources.shutil, "disk_usage", lambda _: SimpleNamespace(free=resources.GIB))
    with pytest.raises(RuntimeError, match="محافظ دیسک"):
        resources.check_resources(tmp_path)


@pytest.mark.parametrize("failed", [False, True])
def test_sleep_request_restores_previous_state_even_when_training_fails(monkeypatch, failed):
    from training.lora import resources

    calls = []

    def fake_state(flags):
        calls.append(flags)
        return 0x80000002  # درخواست قبلی همین thread نیز باید حفظ شود.

    monkeypatch.setattr(resources, "_execution_state", fake_state)
    try:
        with resources.keep_awake():
            if failed:
                raise RuntimeError("training failed")
    except RuntimeError:
        assert failed
    assert calls == [0x80000001, 0x80000002]


def test_runtime_guard_is_checked_between_accumulation_microsteps(tmp_path, monkeypatch):
    from training.lora import train

    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")

    checks = []
    monkeypatch.setattr(train, "check_resources", lambda path: checks.append(path))
    cache_checks = []
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: cache_checks.append(True))
    callback = train._progress_callback(30, tmp_path)
    callback.on_step_begin(None, None, None)
    callback.on_substep_end(None, None, None)
    callback.on_prediction_step(None, None, None)
    assert checks == [tmp_path, tmp_path, tmp_path]
    assert cache_checks == [True]


@pytest.mark.parametrize("normalizer", [None, 32])
def test_discarding_unused_logits_preserves_loss_and_all_adapter_gradients(normalizer):
    from training.lora.train import discard_unused_training_logits

    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("peft")
    torch.manual_seed(9)
    model = apply_lora(
        transformers.Qwen2ForCausalLM(
            transformers.Qwen2Config(
                vocab_size=32,
                hidden_size=16,
                intermediate_size=32,
                num_hidden_layers=1,
                num_attention_heads=4,
                num_key_value_heads=2,
                max_position_embeddings=32,
            )
        ),
        LoraSettings(dropout=0),
    )
    ids = torch.tensor([[1, 2, 3, 4, 5, 6]])
    labels = torch.tensor([[-100, -100, -100, 4, 5, 6]])
    extra = {} if normalizer is None else {"num_items_in_batch": torch.tensor(normalizer)}
    loss = model(input_ids=ids, labels=labels, **extra).loss
    loss.backward()
    gradients = {
        name: parameter.grad.clone() for name, parameter in model.named_parameters() if parameter.requires_grad
    }
    model.zero_grad(set_to_none=True)
    model = discard_unused_training_logits(model)
    output = model(input_ids=ids, labels=labels, **extra)
    assert set(output) == {"loss"}
    assert torch.equal(loss, output["loss"])
    output["loss"].backward()
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            assert torch.equal(gradients[name], parameter.grad), name
    assert model(input_ids=ids).logits.shape == (1, 6, 32)


@pytest.mark.parametrize("steps", ["0", "30", "1032"])
def test_microbenchmark_cannot_request_smoke_or_full_training_length(steps):
    from training.lora.benchmark import parse_args

    with pytest.raises(SystemExit) as error:
        parse_args(["--run-id", "probe", "--steps", steps])
    assert error.value.code == 2


def test_legacy_checkpoint_keeps_native_kernel_policy_and_rejects_switch_on_resume(dataset, tmp_path):
    config = RunConfig(base_model="local", data_dir=dataset, output_root=tmp_path / "outputs")
    config = replace(config, runs_root=tmp_path / "runs", reports_root=tmp_path / "reports")
    prepare_run(config, resume=False)
    manifest_path = config.output_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["config"]["train"].pop("kernel_backend")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (config.output_dir / "checkpoints" / "checkpoint-10").mkdir(parents=True)
    assert prepare_run(config, resume=True).endswith("checkpoint-10")
    different = replace(config, train=replace(config.train, kernel_backend="liger_bf16"))
    with pytest.raises(ValueError, match="پیکربندی"):
        prepare_run(different, resume=True)


def test_fast_preset_preserves_training_recipe_and_effective_batch_size():
    from dataclasses import asdict
    from training.lora.workflow import performance_settings

    native, fast = performance_settings("native"), performance_settings("fast")
    assert native.batch_size * native.grad_accum == fast.batch_size * fast.grad_accum == 16
    allowed = {"batch_size", "grad_accum", "kernel_backend"}
    for name, value in asdict(native).items():
        if name not in allowed:
            assert getattr(fast, name) == value, name


def test_trainer_preserves_effective_batch_gradient_normalization_with_masking_and_padding(tmp_path):
    from training.lora.data import ListDataset, PadCollator
    from training.lora.train import discard_unused_training_logits

    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("peft")
    torch.manual_seed(19)
    base = transformers.Qwen2ForCausalLM(
        transformers.Qwen2Config(
            vocab_size=32,
            hidden_size=16,
            intermediate_size=32,
            num_hidden_layers=1,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=32,
        )
    )
    features = [
        {"input_ids": [1, 2, 3, 4, 5, 6], "labels": [-100, -100, -100, 4, 5, 6]},
        {"input_ids": [7, 8, 9, 10], "labels": [-100, -100, 9, 10]},
        {"input_ids": [11, 12, 13, 14, 15], "labels": [-100, -100, -100, 14, 15]},
        {"input_ids": [16, 17, 18, 19, 20, 21, 22], "labels": [-100, -100, 18, 19, 20, 21, 22]},
    ]
    resulting_weights = []
    for batch in (1, 2, 4):
        torch.manual_seed(42)
        model = discard_unused_training_logits(apply_lora(copy.deepcopy(base), LoraSettings(dropout=0)))
        arguments = transformers.TrainingArguments(
            output_dir=str(tmp_path / str(batch)),
            per_device_train_batch_size=batch,
            gradient_accumulation_steps=4 // batch,
            max_steps=1,
            learning_rate=0.01,
            optim="sgd",
            max_grad_norm=0,
            lr_scheduler_type="constant",
            warmup_steps=0,
            use_cpu=True,
            report_to=[],
            save_strategy="no",
            disable_tqdm=True,
            remove_unused_columns=False,
            label_names=["labels"],
            seed=42,
        )
        trainer = transformers.Trainer(
            model=model,
            args=arguments,
            train_dataset=ListDataset(features),
            data_collator=PadCollator(0, answer_logits_only=True),
        )
        assert trainer.model_accepts_loss_kwargs
        trainer.train()
        resulting_weights.append(
            {
                name: parameter.detach().clone()
                for name, parameter in model.named_parameters()
                if parameter.requires_grad
            }
        )
    for weights in resulting_weights[1:]:
        for name, reference in resulting_weights[0].items():
            assert torch.allclose(weights[name], reference, atol=1e-6, rtol=1e-5), name
