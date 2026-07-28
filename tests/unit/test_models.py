import pytest

from ppa.models import Finding


def test_finding_accepts_bounded_confidence() -> None:
    finding = Finding("Centered compositions recur.", 0.75, ("measurement:placement",))
    assert finding.confidence == 0.75


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_rejects_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        Finding("A neutral statement.", confidence, ())
