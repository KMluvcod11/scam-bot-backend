"""ติดรหัสงานสั้นใน log เดิม และแสดงเวลาแต่ละขั้นโดยไม่เผยข้อมูลคำขอ."""
import builtins
from contextvars import ContextVar
from time import monotonic

trace_id = ContextVar("bot_trace_id", default="-")

# Only known status names may enter logs; never log message/details/response bodies.
ERROR_STATUSES = frozenset({
    "CANCELLED", "UNKNOWN", "INVALID_ARGUMENT", "DEADLINE_EXCEEDED",
    "NOT_FOUND", "ALREADY_EXISTS", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
    "FAILED_PRECONDITION", "ABORTED", "OUT_OF_RANGE", "UNIMPLEMENTED",
    "INTERNAL", "UNAVAILABLE", "DATA_LOSS", "UNAUTHENTICATED",
})


def error_summary(error):
    """Return safe diagnostic fields without formatting the exception itself."""
    fields = [f"type={type(error).__name__}"]
    code = getattr(error, "code", None)
    status = getattr(error, "status", None)
    if type(code) is int and 400 <= code <= 599:
        fields.append(f"code={code}")
    if isinstance(status, str) and status in ERROR_STATUSES:
        fields.append(f"status={status}")
    return " ".join(fields)


def log(*values, **kwargs):
    """ContextVar แยกรหัสแต่ละงาน และถูกส่งต่อไปยัง AnyIO thread pool."""
    kwargs.setdefault("flush", True)
    builtins.print(f"[trace={trace_id.get()}]", *values, **kwargs)


def timed_call(stage, operation, *args, **kwargs):
    """จับเวลาโดยคงค่า return/exception เดิม; returned ไม่ใช่การยืนยัน HTTP success."""
    started = monotonic()
    try:
        result = operation(*args, **kwargs)
    except Exception as error:
        log(f"[ERROR] stage={stage} elapsed={monotonic() - started:.2f}s {error_summary(error)}")
        raise
    outcome = f" returned={str(result).lower()}" if type(result) is bool else ""
    log(f"[TIME] stage={stage} elapsed={monotonic() - started:.2f}s{outcome}")
    return result
