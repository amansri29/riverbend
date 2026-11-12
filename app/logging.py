"""Structured logs. Every line from the pipeline carries shop_id, message_id and job_id so one
message can be followed end to end without a tracing backend.

Two formats, chosen by LOG_FORMAT: `text` for a terminal (default locally, one aligned line per
event) and `json` for Cloud Logging (one object per line). Both carry the same fields.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

# Attributes every LogRecord has; anything else on the record is a field we attached via `extra`.
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}
_CORRELATION = ("shop_id", "message_id", "job_id", "kind", "attempt")


def _fields(record: logging.LogRecord) -> dict:
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD and v is not None}


class JsonFormatter(logging.Formatter):
    """One JSON object per log line with the correlation fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **_fields(record),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """One aligned line per event: time, level, event, correlation ids, other fields, message."""

    def format(self, record: logging.LogRecord) -> str:
        f = _fields(record)
        event = str(f.pop("event", record.name))
        ids = " ".join(f"{k.split('_')[0]}={_short(f.pop(k))}" for k in _CORRELATION if k in f)
        rest = " ".join(f"{k}={_short(v)}" for k, v in f.items())
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"{ts} {record.levelname:<7} {event:<22} {ids:<48} {record.getMessage()}"
        if rest:
            line += f"  [{rest}]"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _short(v: object) -> str:
    s = str(v)
    if len(s) == 36 and s.count("-") == 4:  # a uuid: the first block is enough to follow by eye
        return s[:8]
    return s if len(s) <= 80 else s[:77] + "..."


def configure(level: str = "INFO", fmt: str = "text") -> None:
    """Install logging on the root logger in the chosen format."""
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root.addHandler(h)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    for noisy in ("httpx", "httpcore", "openai", "google", "urllib3"):
        logging.getLogger(noisy).setLevel("WARNING")
