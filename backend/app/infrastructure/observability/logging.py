import logging

from backend.app.config import Settings
from backend.app.infrastructure.observability.request_context import get_request_id


class _DefaultLogContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", get_request_id())
        record.workflow_id = getattr(record, "workflow_id", "-")
        record.order_intent_id = getattr(record, "order_intent_id", "-")
        record.recommendation_id = getattr(record, "recommendation_id", "-")
        record.event_count = getattr(record, "event_count", "-")
        record.duration_ms = getattr(record, "duration_ms", "-")
        record.status_code = getattr(record, "status_code", "-")
        record.method = getattr(record, "method", "-")
        record.path = getattr(record, "path", "-")
        return True


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            (
                "%(asctime)s %(levelname)s %(name)s %(message)s "
                "request_id=%(request_id)s workflow_id=%(workflow_id)s "
                "order_intent_id=%(order_intent_id)s recommendation_id=%(recommendation_id)s "
                "event_count=%(event_count)s duration_ms=%(duration_ms)s "
                "method=%(method)s path=%(path)s status_code=%(status_code)s"
            )
        )
    )
    handler.addFilter(_DefaultLogContextFilter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)
