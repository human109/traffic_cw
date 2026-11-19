"""스케줄러 테스트. 가짜 step만 실행하고, 실제 진입점은 import·식별만 확인한다 (네트워크·DB 없음)."""

from __future__ import annotations

import logging
from datetime import datetime

import pytest

from collector import scheduler
from collector.scheduler import build_scheduler, main, run_pipeline
from common.records import CollectionResult
from common.timeutil import KST
from config.settings import Settings

NOW = datetime(2026, 11, 16, 7, 5, 30, tzinfo=KST)
ORDER = ["collect", "preprocess", "backfill", "predict"]
FAKE_KEY = "SECRET123"


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """키 가리기용 설정 로드가 실제 .env를 읽지 않게 가짜 설정으로 바꾼다."""
    monkeypatch.setattr("config.settings.get_settings", lambda: Settings(its_api_key=FAKE_KEY))


def _recording_steps(calls: list[tuple[str, datetime]], fail: str | None = None, exc: Exception | None = None):
    def make(name: str):
        def step(now: datetime) -> object:
            calls.append((name, now))
            if name == fail:
                raise exc or RuntimeError("synthetic")
            return 1

        return step

    return [(name, make(name)) for name in ORDER]


def _collection(status: str) -> CollectionResult:
    return CollectionResult(
        source="its",
        status=status,  # type: ignore[arg-type]
        started_at=NOW,
        finished_at=NOW,
        http_status=None,
        links_expected=None,
        links_received=0,
        record_count=0,
        error_message=None,
    )


def _steps_with_collect(calls: list[str], status: str) -> list[tuple[str, object]]:
    def make(name: str):
        def step(now: datetime) -> object:
            calls.append(name)
            return _collection(status) if name == "collect" else 1

        return step

    return [(name, make(name)) for name in ORDER]


@pytest.mark.parametrize(
    ("status", "expected", "exit_code"),
    [
        ("failed", "error: failed", 1),
        ("auth_error", "error: auth_error", 1),
        ("success", "success", 0),
        ("partial", "partial", 0),
        ("no_update", "no_update", 0),
    ],
)
def test_collection_status_reported(
    monkeypatch: pytest.MonkeyPatch, status: str, expected: str, exit_code: int
) -> None:
    calls: list[str] = []
    result = run_pipeline(NOW, _steps_with_collect(calls, status))  # type: ignore[arg-type]
    assert result == {"collect": expected, "preprocess": "ok", "backfill": "ok", "predict": "ok"}
    assert calls == ORDER  # 수집이 실패해도 다음 단계는 실행

    calls.clear()
    monkeypatch.setattr(scheduler, "_default_steps", lambda: _steps_with_collect(calls, status))
    assert main(["--once"]) == exit_code
    assert calls == ORDER


def test_order() -> None:
    calls: list[tuple[str, datetime]] = []
    result = run_pipeline(NOW, _recording_steps(calls))
    assert [c[0] for c in calls] == ORDER
    assert all(c[1] == NOW for c in calls)
    assert result == {name: "ok" for name in ORDER}
    assert list(result) == ORDER


def test_failure_isolated(caplog: pytest.LogCaptureFixture) -> None:
    calls: list[tuple[str, datetime]] = []
    # 키가 apiKey= 뒤뿐 아니라 맨 문자열로도 섞인 경우: 실제 키 값으로도 가려야 한다.
    exc = RuntimeError(f"boom apiKey={FAKE_KEY}&type=all key={FAKE_KEY}")
    result = run_pipeline(NOW, _recording_steps(calls, fail="preprocess", exc=exc))
    assert result == {"collect": "ok", "preprocess": "error: RuntimeError", "backfill": "ok", "predict": "ok"}
    assert [c[0] for c in calls] == ORDER  # 실패 뒤 단계도 실행
    assert FAKE_KEY not in caplog.text
    assert "RuntimeError" in caplog.text


def test_mask_falls_back_when_settings_fail(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> Settings:
        raise RuntimeError("settings broken")

    monkeypatch.setattr("config.settings.get_settings", boom)
    exc = RuntimeError(f"boom apiKey={FAKE_KEY}")
    result = run_pipeline(NOW, [("collect", lambda now: (_ for _ in ()).throw(exc))])
    assert result == {"collect": "error: RuntimeError"}
    assert FAKE_KEY not in caplog.text


@pytest.mark.parametrize("target", ["_default_steps", "run_pipeline"])
def test_scheduled_job_swallows_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, target: str
) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise ImportError(f"synthetic {target} failure {FAKE_KEY}")

    monkeypatch.setattr(scheduler, target, boom)
    assert scheduler._scheduled_job() is None  # 예외 없이 정상 반환
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors
    assert "ImportError" in caplog.text
    assert FAKE_KEY not in caplog.text


def test_evaluate_once_calls_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """평가 job은 C-06 진입점 `prediction.evaluate`만 호출한다."""
    import prediction

    seen: list[datetime] = []
    monkeypatch.setattr(prediction, "evaluate", lambda now, conn=None, days=7: seen.append(now) or 7)
    assert scheduler._evaluate_once(NOW) == 7
    assert seen == [NOW]


def test_scheduled_evaluate_job_swallows_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(now: datetime) -> int:
        raise RuntimeError(f"synthetic evaluate failure {FAKE_KEY}")

    monkeypatch.setattr(scheduler, "_evaluate_once", boom)
    assert scheduler._scheduled_evaluate_job() is None  # 예외 없이 정상 반환
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors
    assert "RuntimeError" in caplog.text
    assert FAKE_KEY not in caplog.text  # 키 가리기


def test_main_evaluate_runs_only_evaluate(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline_calls: list[datetime] = []
    evaluate_calls: list[datetime] = []
    monkeypatch.setattr(scheduler, "run_pipeline", lambda now, steps=None: pipeline_calls.append(now) or {})
    monkeypatch.setattr(scheduler, "_evaluate_once", lambda now: evaluate_calls.append(now) or 3)
    assert main(["--evaluate"]) == 0
    assert pipeline_calls == []  # 파이프라인은 호출하지 않는다
    assert len(evaluate_calls) == 1
    assert evaluate_calls[0].utcoffset() == KST.utcoffset(None)


def test_main_evaluate_failure_exit_code(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(now: datetime) -> int:
        raise RuntimeError(f"synthetic evaluate failure {FAKE_KEY}")

    monkeypatch.setattr(scheduler, "_evaluate_once", boom)
    assert main(["--evaluate"]) == 1
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors
    assert "RuntimeError" in caplog.text
    assert FAKE_KEY not in caplog.text


def test_main_maintenance(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    seen: list[datetime] = []
    monkeypatch.setattr(scheduler, "_backup_once", lambda now: seen.append(now) or calls.append("backup"))
    monkeypatch.setattr(scheduler, "_prune_once", lambda now: seen.append(now) or calls.append("prune_raw"))
    assert main(["--maintenance"]) == 0
    assert calls == ["backup", "prune_raw"]  # 백업 → 원본 정리 순서로 1회 실행
    assert len(seen) == 2 and all(n.utcoffset() == KST.utcoffset(None) for n in seen)


def test_main_maintenance_failure_exit_code(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []

    def boom(now: datetime) -> object:
        calls.append("backup")
        raise RuntimeError(f"synthetic maintenance failure {FAKE_KEY}")

    monkeypatch.setattr(scheduler, "_backup_once", boom)
    monkeypatch.setattr(scheduler, "_prune_once", lambda now: calls.append("prune_raw"))
    assert main(["--maintenance"]) == 1
    assert calls == ["backup", "prune_raw"]  # 실패해도 다음 단계는 실행됐다
    assert "RuntimeError" in caplog.text
    assert FAKE_KEY not in caplog.text


def test_main_once_evaluate_skips_evaluation_when_pipeline_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    evaluate_calls: list[datetime] = []
    monkeypatch.setattr(
        scheduler, "run_pipeline", lambda now, steps=None: {"collect": "error: failed", "predict": "ok"}
    )
    monkeypatch.setattr(scheduler, "_evaluate_once", lambda now: evaluate_calls.append(now) or 1)
    assert main(["--once", "--evaluate"]) == 1
    assert evaluate_calls == []  # 파이프라인이 실패하면 평가는 건너뛴다 (리뷰 Minor)


def test_main_once_evaluate_runs_both_when_pipeline_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    evaluate_calls: list[datetime] = []
    monkeypatch.setattr(scheduler, "run_pipeline", lambda now, steps=None: {name: "ok" for name in ORDER})
    monkeypatch.setattr(scheduler, "_evaluate_once", lambda now: evaluate_calls.append(now) or 1)
    assert main(["--once", "--evaluate"]) == 0
    assert len(evaluate_calls) == 1


def test_naive_now_rejected() -> None:
    calls: list[tuple[str, datetime]] = []
    with pytest.raises(ValueError):
        run_pipeline(datetime(2026, 11, 16, 7, 5), _recording_steps(calls))
    assert calls == []


def test_default_steps_use_entrypoints() -> None:
    preprocessing = pytest.importorskip("preprocessing")
    if not hasattr(preprocessing, "run"):
        pytest.skip("preprocessing.run 진입점이 아직 없다 (Task 6)")
    import collector
    import prediction

    steps = scheduler._default_steps()
    assert [name for name, _ in steps] == ORDER
    targets = [getattr(fn, "__wrapped__", fn) for _, fn in steps]
    assert targets == [
        collector.run_once,
        preprocessing.run,
        prediction.backfill_actuals,
        prediction.predict_latest,
    ]


def test_build_scheduler_jobs() -> None:
    # 기본이 아닌 값으로 만들어 trigger가 settings를 따르는지 본다.
    settings = Settings(collect_cron_minute="*/5", eval_cron_hour=9, eval_cron_minute=55, backup_cron_hour=4)
    sched = build_scheduler(settings)
    jobs = {job.id: job for job in sched.get_jobs()}
    assert set(jobs) == {"pipeline", "evaluate", "maintenance"}  # job 3개

    pipeline = jobs["pipeline"]
    fields = {f.name: str(f) for f in pipeline.trigger.fields}
    assert fields["minute"] == "*/5"
    assert fields["second"] == "30"
    assert pipeline.trigger.timezone.utcoffset(None) == KST.utcoffset(None)
    assert pipeline.max_instances == 1
    assert pipeline.coalesce is True
    assert pipeline.misfire_grace_time == settings.scheduler_misfire_grace_s

    evaluate = jobs["evaluate"]
    fields = {f.name: str(f) for f in evaluate.trigger.fields}
    assert fields["hour"] == "9"  # settings.eval_cron_hour
    assert fields["minute"] == "55"  # settings.eval_cron_minute
    assert fields["second"] == "0"
    assert evaluate.trigger.timezone.utcoffset(None) == KST.utcoffset(None)
    assert evaluate.max_instances == 1
    assert evaluate.coalesce is True
    assert evaluate.misfire_grace_time == settings.scheduler_misfire_grace_s
    assert evaluate.func is scheduler._scheduled_evaluate_job

    maintenance = jobs["maintenance"]
    fields = {f.name: str(f) for f in maintenance.trigger.fields}
    assert fields["hour"] == "4"  # settings.backup_cron_hour
    assert fields["minute"] == "0"
    assert fields["second"] == "0"
    assert maintenance.trigger.timezone.utcoffset(None) == KST.utcoffset(None)
    assert maintenance.max_instances == 1
    assert maintenance.coalesce is True
    assert maintenance.misfire_grace_time == settings.scheduler_misfire_grace_s
    assert maintenance.func is scheduler._scheduled_maintenance_job


def test_run_maintenance_runs_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(scheduler, "_backup_once", lambda now: calls.append("backup") or NOW)
    monkeypatch.setattr(scheduler, "_prune_once", lambda now: calls.append("prune_raw") or 7)
    results = scheduler.run_maintenance(NOW)
    assert calls == ["backup", "prune_raw"]  # 백업 → 원본 정리 순서
    assert results == {"backup": "ok", "prune_raw": "ok"}


def test_run_maintenance_isolates_failures(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    calls: list[str] = []

    def boom(now: datetime) -> object:
        calls.append("backup")
        raise RuntimeError(f"synthetic backup failure {FAKE_KEY}")

    monkeypatch.setattr(scheduler, "_backup_once", boom)
    monkeypatch.setattr(scheduler, "_prune_once", lambda now: calls.append("prune_raw") or 3)
    results = scheduler.run_maintenance(NOW)
    assert calls == ["backup", "prune_raw"]  # 백업이 실패해도 원본 정리는 실행한다
    assert results == {"backup": "error: RuntimeError", "prune_raw": "ok"}
    assert "RuntimeError" in caplog.text
    assert FAKE_KEY not in caplog.text  # 키 가리기


def test_run_maintenance_naive_now_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(scheduler, "_backup_once", lambda now: calls.append("backup"))
    monkeypatch.setattr(scheduler, "_prune_once", lambda now: calls.append("prune_raw"))
    with pytest.raises(ValueError):
        scheduler.run_maintenance(datetime(2026, 11, 20, 11, 0))
    assert calls == []  # 어떤 단계도 실행하지 않는다


def test_scheduled_maintenance_job_swallows_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(now: datetime) -> object:
        raise RuntimeError(f"synthetic maintenance failure {FAKE_KEY}")

    monkeypatch.setattr(scheduler, "run_maintenance", boom)
    assert scheduler._scheduled_maintenance_job() is None  # 예외 없이 정상 반환
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors
    assert "RuntimeError" in caplog.text
    assert FAKE_KEY not in caplog.text


def test_backup_once_calls_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    backup_mod = pytest.importorskip("scripts.backup_db")  # dev-data 모듈. 없으면 이 테스트는 건너뛴다.
    seen: list[datetime] = []
    monkeypatch.setattr(backup_mod, "backup", lambda now, conn=None: seen.append(now) or NOW)
    assert scheduler._backup_once(NOW) == NOW
    assert seen == [NOW]


def test_prune_once_applies_deletion(monkeypatch: pytest.MonkeyPatch) -> None:
    from collector import maintenance

    seen: list[tuple[datetime, bool]] = []
    monkeypatch.setattr(maintenance, "prune_raw", lambda now, settings=None, dry_run=True: seen.append((now, dry_run)) or 5)
    assert scheduler._prune_once(NOW) == 5
    assert seen == [(NOW, False)]  # 스케줄러 운영 job은 실제 삭제(apply)로 실행한다


def test_main_once(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[datetime] = []

    def fake_pipeline(now: datetime, steps: object = None) -> dict[str, str]:
        seen.append(now)
        return {name: "ok" for name in ORDER}

    monkeypatch.setattr(scheduler, "run_pipeline", fake_pipeline)
    assert main(["--once"]) == 0
    assert len(seen) == 1
    assert seen[0].utcoffset() == KST.utcoffset(None)


def test_main_once_reports_failure(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(
        scheduler, "run_pipeline", lambda now, steps=None: {"collect": "ok", "preprocess": "error: RuntimeError"}
    )
    assert main(["--once"]) == 1
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("preprocess" in m for m in warnings)
