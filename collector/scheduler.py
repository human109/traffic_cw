"""파이프라인·평가 스케줄러 (SPEC 7.6). 실행: `python -m collector.scheduler [--once] [--evaluate]`.

수집 → 전처리 → 실제값 갱신 → 예측 순서로 각 모듈의 C-06 진입점만 호출한다. 내부 함수는 import하지 않는다.
상주 실행 시 job 2개: 파이프라인(매 5분 xx:x0:30/xx:x5:30)과 일일 평가(매일 10:05:00 KST).
"""

from __future__ import annotations

import argparse
import functools
from collections.abc import Callable, Sequence
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from collector.its import mask_secret
from common.logsetup import get_logger
from common.records import CollectionResult
from common.timeutil import KST, now_kst, require_aware, to_iso
from config.settings import Settings

# M7: `python -m collector.scheduler`로 실행하면 `__name__`이 `__main__`이 되므로 이름을 고정한다.
log = get_logger("collector.scheduler")

Step = Callable[[datetime], object]

JOB_ID = "pipeline"
JOB_ID_EVALUATE = "evaluate"
CRON_SECOND = 30  # 매 회차 xx:x0:30 / xx:x5:30. 갱신 직후 원본이 준비될 시간을 둔다.
# 일일 평가 job (Slice 1 Task 6). 매일 10:05:00 KST에 최근 7일을 평가한다(C-06 evaluate 기본 days=7).
EVAL_HOUR = 10
EVAL_MINUTE = 5
EVAL_SECOND = 0


def _as_step(fn: Callable[..., object], arg_name: str) -> Step:
    """진입점 `fn`을 `now` 하나만 받는 step으로 감싼다. `__wrapped__`로 원래 진입점을 알 수 있다."""

    @functools.wraps(fn)
    def step(now: datetime) -> object:
        return fn(**{arg_name: now})

    return step


def _default_steps() -> list[tuple[str, Step]]:
    """기본 단계: collect → preprocess → backfill → predict. 진입점은 호출 시점에 지연 import한다."""
    import collector
    import prediction
    import preprocessing

    return [
        ("collect", _as_step(collector.run_once, "now")),
        ("preprocess", _as_step(preprocessing.run, "until")),
        ("backfill", _as_step(prediction.backfill_actuals, "now")),
        ("predict", _as_step(prediction.predict_latest, "now")),
    ]


def run_pipeline(now: datetime, steps: Sequence[tuple[str, Step]] | None = None) -> dict[str, str]:
    """단계를 순서대로 실행하고 단계별 결과 문자열을 돌려준다.

    - 예외 → `"error: <예외 클래스 이름>"`
    - `CollectionResult` 반환 → `"success"`·`"partial"`·`"no_update"` 또는 `"error: failed"`·`"error: auth_error"`
    - 그 밖의 반환 → `"ok"`
    `"error: "`로 시작하는 값이 실패다(`is_failure`).

    한 단계가 실패해도 다음 단계를 실행한다. 예외 메시지는 결과에 넣지 않고 키를 가려 로그에만 남긴다.
    `now`가 timezone 정보 없는 datetime이면 `ValueError`(어떤 단계도 실행하지 않는다).
    기본 단계를 import하지 못하면(모듈 미구현 등) 그 예외는 호출자에게 전달된다.
    """
    require_aware(now)  # tz 없는 datetime 거부
    if steps is None:
        steps = _default_steps()
    results: dict[str, str] = {}
    for name, step in steps:
        try:
            results[name] = _outcome(step(now))
        except Exception as e:
            results[name] = f"error: {type(e).__name__}"
            # traceback에는 키가 섞인 URL이 들어갈 수 있어 가린 메시지만 남긴다.
            log.error("파이프라인 단계 %s 실패: %s", name, _masked(e))
    log.info("파이프라인 %s: %s", to_iso(now), results)
    return results


_FAILED_COLLECTION = frozenset({"failed", "auth_error"})


def _outcome(value: object) -> str:
    """step 반환값을 결과 문자열로 바꾼다.

    `CollectionResult`이면 수집 실패가 정상처럼 보이지 않게 상태를 드러낸다 (SPEC 4.5):
    `failed`·`auth_error` → `"error: <status>"`, 그 밖(`success`·`partial`·`no_update`) → `"<status>"`.
    다른 반환값은 예외 없이 끝났으므로 `"ok"`.
    """
    if isinstance(value, CollectionResult):
        return f"error: {value.status}" if value.status in _FAILED_COLLECTION else value.status
    return "ok"


def is_failure(outcome: str) -> bool:
    """`run_pipeline` 결과 값이 실패인지 (`"error: "`로 시작)."""
    return outcome.startswith("error: ")


def _secret() -> str | None:
    """가릴 실제 키 값. 설정을 읽지 못하면 None(그래도 `apiKey=` 패턴은 가린다)."""
    try:
        from config.settings import get_settings

        return get_settings().its_api_key
    except Exception:
        return None


def _masked(e: BaseException) -> str:
    """예외를 `클래스: 메시지` 문자열로 만들고 키를 가린다."""
    return mask_secret(f"{type(e).__name__}: {e}", _secret())


def _scheduled_job() -> None:
    """스케줄러가 매 회차 호출한다. 어떤 예외도 스케줄러로 새지 않게 막고 에러 로그를 남긴다."""
    try:
        run_pipeline(now_kst())
    except Exception as e:
        log.error("파이프라인 실행 실패: %s", _masked(e))


def _evaluate_once(now: datetime) -> int:
    """평가 진입점을 1회 실행한다. 진입점은 호출 시점에 지연 import한다 (C-06 v2)."""
    import prediction

    return prediction.evaluate(now)


def _scheduled_evaluate_job() -> None:
    """스케줄러가 매일 10:05 호출한다. 파이프라인 job과 같은 예외 내성·키 가리기를 쓴다."""
    try:
        count = _evaluate_once(now_kst())
    except Exception as e:
        log.error("평가 실행 실패: %s", _masked(e))
        return
    log.info("평가 완료: model_evaluation %d행", count)


def build_scheduler(settings: Settings) -> BlockingScheduler:
    """파이프라인 job과 일일 평가 job을 등록한 `BlockingScheduler`를 만든다(시작하지 않음).

    - 파이프라인: CronTrigger(minute=settings.collect_cron_minute, second=30, timezone=KST)
    - 평가: CronTrigger(hour=10, minute=5, second=0, timezone=KST), `prediction.evaluate(now, days=7)`
    - 두 job 모두 max_instances=1(이전 실행이 끝나지 않으면 겹쳐 실행하지 않음),
      coalesce=True(밀린 회차는 1회로 합침),
      misfire_grace_time=settings.scheduler_misfire_grace_s(예정 시각에서 이 초 안에 깨어나면 실행하고,
      더 늦으면 PC 절전 등 건너뛴다).
    """
    sched = BlockingScheduler(timezone=KST)
    sched.add_job(
        _scheduled_job,
        CronTrigger(minute=settings.collect_cron_minute, second=CRON_SECOND, timezone=KST),
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.scheduler_misfire_grace_s,
    )
    sched.add_job(
        _scheduled_evaluate_job,
        CronTrigger(hour=EVAL_HOUR, minute=EVAL_MINUTE, second=EVAL_SECOND, timezone=KST),
        id=JOB_ID_EVALUATE,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.scheduler_misfire_grace_s,
    )
    return sched


def main(argv: list[str] | None = None) -> int:
    """`--once`이면 파이프라인을, `--evaluate`이면 평가를 1회 실행하고 끝낸다.

    둘 다 주면 순서대로 실행한다. 파이프라인 단계 하나라도 `"error: "`로 시작하면, 또는 평가에서
    예외가 나면 1, 아니면 0을 반환한다. 인자가 없으면 스케줄러를 상주 실행한다(Ctrl+C로 종료, 0 반환).
    """
    parser = argparse.ArgumentParser(prog="python -m collector.scheduler", description="수집·전처리·예측 파이프라인")
    parser.add_argument("--once", action="store_true", help="파이프라인을 1회 실행하고 끝낸다")
    parser.add_argument("--evaluate", action="store_true", help="평가(prediction.evaluate)를 1회 실행하고 끝난다")
    args = parser.parse_args(argv)

    if args.once:
        results = run_pipeline(now_kst())
        failed = {k: v for k, v in results.items() if is_failure(v)}
        if failed:
            log.warning("파이프라인 1회 실행 중 실패한 단계: %s", failed)
            return 1
        if not args.evaluate:
            return 0

    if args.evaluate:
        try:
            count = _evaluate_once(now_kst())
        except Exception as e:
            log.error("평가 1회 실행 실패: %s", _masked(e))
            return 1
        log.info("평가 1회 실행: model_evaluation %d행", count)

    if not args.once and not args.evaluate:
        from config.settings import get_settings

        settings = get_settings()
        sched = build_scheduler(settings)
        log.info(
            "스케줄러 시작: 파이프라인 minute=%s second=%d, 평가 매일 %02d:%02d:%02d (KST)",
            settings.collect_cron_minute, CRON_SECOND, EVAL_HOUR, EVAL_MINUTE, EVAL_SECOND,
        )
        try:
            sched.start()
        except (KeyboardInterrupt, SystemExit):
            if sched.running:
                sched.shutdown(wait=False)
            log.info("스케줄러 종료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
