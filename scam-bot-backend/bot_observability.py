"""ติดรหัสงานสั้นใน log เดิม และแสดงเวลารอเฉพาะเมื่อ API ผิดพลาด."""
import builtins
from contextvars import ContextVar
from time import monotonic

trace_id = ContextVar("bot_trace_id", default="-")


def log(*values, **kwargs):
    """ContextVar แยกรหัสแต่ละงาน และถูกส่งต่อไปยัง AnyIO thread pool."""
    kwargs.setdefault("flush", True)
    builtins.print(f"[trace={trace_id.get()}]", *values, **kwargs)


def timed_call(stage, operation, *args, **kwargs):
    """เมื่อสำเร็จไม่เพิ่ม log; เมื่อผิดพลาดแสดงขั้นตอนและเวลาแล้วส่ง exception ต่อ."""
    started = monotonic()
    try:
        result = operation(*args, **kwargs)
    except Exception as error:
        log(f"[ERROR] stage={stage} elapsed={monotonic() - started:.2f}s type={type(error).__name__}")
        raise
    return result
