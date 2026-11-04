import asyncio

from desk.llm import LLMConfig, Wording
from desk.models import Extraction, Verdict


def test_rules_mode_keeps_the_templated_explanation_and_the_code_amount():
    wording = Wording(LLMConfig(mode="rules", base_url="", api_key="", model=""))
    verdict = Verdict(status="FLAG", reasons=["over the cap"], explanation="C-001 is FLAG.")
    text = asyncio.run(wording.polish_explanation(verdict, "pizza"))
    assert text == "C-001 is FLAG."
    extraction = Extraction(
        amount="42.30",
        currency="USD",
        spent_on="2026-11-03",
        category="other",
        event="unspecified",
        receipt_ref="",
        raw="pizza",
    )
    labeled = asyncio.run(wording.suggest_labels(extraction))
    assert labeled.amount == "42.30"
    assert labeled.spent_on == "2026-11-03"
    assert labeled.category == "other"


def test_live_without_a_key_stays_on_the_template():
    wording = Wording(LLMConfig(mode="live", base_url="http://example.invalid", api_key="", model="demo"))
    assert wording.config.live is False
    assert "no LLM_API_KEY" in wording.config.label()
