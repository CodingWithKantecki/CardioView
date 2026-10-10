"""The model card says what the models are, what they are not, and carries the results."""
from research.rhythm import publish


def test_the_card_carries_the_results_and_the_plain_statements():
    results = "# Rhythm feasibility: results\n\n| Condition | Verdict at 130 Hz |\n|---|---|\n| Atrial fibrillation | pass |\n"
    text = publish.card(results, "mit")
    assert text.startswith("---\nlicense: mit\n")
    assert "| Atrial fibrillation | pass |" in text and "# Rhythm feasibility: results" not in text
    assert "not a medical device" in text and "PTB-XL" in text and "CC BY 4.0" in text
