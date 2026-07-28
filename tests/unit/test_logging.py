import json
import logging

from ppa.core.logging import JsonFormatter


def test_json_formatter_preserves_structured_context() -> None:
    record = logging.LogRecord("ppa.test", logging.INFO, __file__, 1, "ready", (), None)
    record.portfolio_id = "portfolio-1"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "ready"
    assert payload["portfolio_id"] == "portfolio-1"
