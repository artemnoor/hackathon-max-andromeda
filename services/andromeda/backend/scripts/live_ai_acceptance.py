"""Explicit, bounded live acceptance for the optional presentation provider."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from andromeda.infrastructure.adapters.polza_naturalizer import PolzaNaturalizer
from andromeda.infrastructure.config.settings import Settings
from andromeda.modules.presentation.contracts.knowledge_response import (
    KnowledgeAnswerState,
    KnowledgeResponseSection,
    ResponseActionability,
    ResponseFact,
    ResponseMode,
    ResponseUncertainty,
)
from andromeda.modules.presentation.services.knowledge_response import (
    KnowledgeResponseRenderer,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run an explicit live DeepSeek presentation acceptance check."
    )
    parser.add_argument("--provider", choices=("deepseek",), required=True)
    parser.add_argument("--max-calls", type=int, choices=range(1, 6), default=1)
    args = parser.parse_args(argv)

    settings = Settings.from_environment()
    if not settings.presentation_llm_enabled:
        print(json.dumps({"status": "unavailable", "reason": "feature_disabled"}))
        return 2
    if settings.polza_api_key is None:
        print(
            json.dumps({"status": "unavailable", "reason": "POLZA_AI_API_KEY_missing"})
        )
        return 2

    naturalizer = PolzaNaturalizer(settings)
    renderer = KnowledgeResponseRenderer(naturalizer=naturalizer)
    accepted = 0
    for index in range(args.max_calls):
        result = renderer.render(
            _synthetic_response(),
            rate_limit_key=f"live-acceptance-fixture-{index}",
        )
        if result.response_mode is not ResponseMode.SOURCE_BACKED_VERBALIZATION:
            print(
                json.dumps(
                    {
                        "status": "failed_closed",
                        "provider": args.provider,
                        "calls_attempted": index + 1,
                        "accepted": accepted,
                        "reason": "provider_unavailable_or_output_rejected",
                    }
                )
            )
            return 1
        accepted += 1
    print(
        json.dumps(
            {
                "status": "passed",
                "provider": args.provider,
                "model": settings.deepseek_model,
                "calls_attempted": accepted,
                "accepted": accepted,
                "fixture": "synthetic_non-production-payload",
            }
        )
    )
    return 0


def _synthetic_response() -> KnowledgeResponseSection:
    return KnowledgeResponseSection(
        status=KnowledgeAnswerState.SOURCE_ASSERTION,
        actionability=ResponseActionability.INFORMATIONAL,
        known_facts=(
            ResponseFact(
                label="Тестовый материал",
                value=(
                    "Это синтетический fixture для проверки только presentation-пути; "
                    "он не описывает реальное правило, вуз, заявителя или приёмную "
                    "кампанию. В этом fixture указано, что демонстрационный проект "
                    "условного документа опубликован, дата вступления в силу не "
                    "указана, область действия остаётся неопределённой, а сведения "
                    "не должны использоваться для принятия решений. Проверка "
                    "подтверждает только сохранение переданных слов, статуса, "
                    "неопределённости и typed section references."
                ),
            ),
            ResponseFact(
                label="Ограничение",
                value="fixture не является источником фактов или юридической нормой",
            ),
        ),
        uncertainties=(ResponseUncertainty.EFFECTIVE_DATE_UNKNOWN,),
    )


if __name__ == "__main__":
    raise SystemExit(main())
