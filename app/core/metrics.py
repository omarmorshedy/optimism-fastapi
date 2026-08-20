"""Prometheus metrics (ADR-012, arc42 §8.2.2)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP request volume",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
BOOKING_CREATED = Counter(
    "booking_created_total",
    "Booking creation outcomes",
    ["resource_id", "status"],
)
BOOKING_CANCELLED = Counter(
    "booking_cancelled_total",
    "Booking cancellations",
    ["resource_id"],
)
EMAIL_OUTBOX_PENDING = Gauge(
    "email_outbox_pending",
    "Pending email outbox entries",
)
EMAIL_SENT = Counter(
    "email_sent_total",
    "Email send outcomes",
    ["status"],
)
DB_POOL_USAGE = Gauge(
    "db_pool_usage",
    "Database connection pool usage (checked-out connections)",
)
DB_POOL_MAX = Gauge(
    "db_pool_max",
    "Database connection pool maximum size",
)
EMAIL_WORKER_ALIVE = Gauge(
    "email_worker_alive",
    "1 if the email worker heartbeat is fresh, else 0",
)
RATE_LIMIT_EXCEEDED = Counter(
    "rate_limit_exceeded_total",
    "Rate-limit hits",
    ["endpoint"],
)
