import redis
import json
import time
import logging
import socket
import random
import os
import threading
from datetime import datetime, timedelta
from pythonjsonlogger import jsonlogger
from flask import Flask, jsonify
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
STREAM_KEY = "notes_stream"
GROUP_NAME = "notes_processors"
CONSUMER_NAME = f"worker-{socket.gethostname()}"
DLQ_KEY = "notes_stream_dlq"
PROCESSED_SET_KEY = "processed_notes"

RETRY_SCHEDULE_ZSET_KEY = "notes_stream_retry_schedule"
RETRY_PAYLOAD_HASH_KEY = "notes_stream_retry_payloads"

MAX_RETRIES = 3
IDLE_TIME_MS = 60000
BASE_DELAY_SEC = 2
MAX_DELAY_SECONDS = 60

HEALTH_FILE = "/tmp/healthy"
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", 8080))

# ═══════════════════════════════════════════════════════════════════════════════
# PROMETHEUS METRICS
# ═══════════════════════════════════════════════════════════════════════════════
MESSAGES_PROCESSED = Counter(
    "messages_processed_total",
    "Total number of messages successfully processed",
    ["consumer", "event_type"],
)

RETRIES_TOTAL = Counter(
    "retries_total",
    "Total number of retries scheduled",
    ["consumer"],
)

DLQ_TOTAL = Counter(
    "dlq_total",
    "Total number of messages sent to DLQ",
    ["consumer"],
)

PROCESSING_DURATION = Histogram(
    "processing_duration_ms",
    "Message processing duration in milliseconds",
    ["consumer", "event_type"],
    buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
)

CONSUMER_LAG = Gauge(
    "consumer_lag",
    "Number of pending messages for this consumer group",
    ["consumer", "group"],
)

REDIS_CONNECTED = Gauge(
    "redis_connected",
    "1 if connected to Redis, 0 otherwise",
    ["consumer"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING WITH CORRELATION
# ═══════════════════════════════════════════════════════════════════════════════
class CorrelatedJsonFormatter(jsonlogger.JsonFormatter):
    """Adds consumer_name to every log record."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["consumer"] = CONSUMER_NAME


logger = logging.getLogger()
handler = logging.StreamHandler()
handler.setFormatter(CorrelatedJsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH FILE
# ═══════════════════════════════════════════════════════════════════════════════
def touch_health_file() -> None:
    os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        f.write(str(time.time()))

# ═══════════════════════════════════════════════════════════════════════════════
# REDIS CONNECTION
# ═══════════════════════════════════════════════════════════════════════════════
r: redis.Redis = None  # type: ignore


def connect_to_redis() -> redis.Redis:
    global r
    while True:
        try:
            client = redis.Redis(host="redis", port=6379, decode_responses=True)
            client.ping()
            logger.info("Connected to Redis")
            REDIS_CONNECTED.labels(consumer=CONSUMER_NAME).set(1)
            r = client
            return client
        except redis.exceptions.ConnectionError:
            logger.warning("Waiting for Redis...")
            REDIS_CONNECTED.labels(consumer=CONSUMER_NAME).set(0)
            touch_health_file()
            time.sleep(2)


def check_redis_health() -> bool:
    try:
        r.ping()
        REDIS_CONNECTED.labels(consumer=CONSUMER_NAME).set(1)
        return True
    except Exception:
        REDIS_CONNECTED.labels(consumer=CONSUMER_NAME).set(0)
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# CONSUMER LAG
# ═══════════════════════════════════════════════════════════════════════════════
def get_consumer_lag() -> int:
    """Return total pending messages for the consumer group."""
    try:
        info = r.xpending(STREAM_KEY, GROUP_NAME)
        pending = info.get("pending", 0) if isinstance(info, dict) else (info[0] if info else 0)
        CONSUMER_LAG.labels(consumer=CONSUMER_NAME, group=GROUP_NAME).set(pending)
        return pending
    except Exception:
        return -1

# ═══════════════════════════════════════════════════════════════════════════════
# FLASK HEALTH / METRICS SERVER
# ═══════════════════════════════════════════════════════════════════════════════
app = Flask(__name__)


@app.route("/health")
def health():
    redis_ok = check_redis_health()
    lag = get_consumer_lag()
    status = "healthy" if redis_ok else "unhealthy"
    code = 200 if redis_ok else 503
    return jsonify({
        "status": status,
        "consumer": CONSUMER_NAME,
        "redis_connected": redis_ok,
        "consumer_lag": lag,
    }), code


@app.route("/metrics")
def metrics():
    # Update lag before scrape
    get_consumer_lag()
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


def start_health_server():
    """Run Flask in a background daemon thread."""
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=HEALTH_PORT, threaded=True),
        daemon=True,
    )
    thread.start()
    logger.info("Health server started", extra={"port": HEALTH_PORT})

# ═══════════════════════════════════════════════════════════════════════════════
# CONSUMER GROUP SETUP
# ═══════════════════════════════════════════════════════════════════════════════
def ensure_consumer_group():
    try:
        r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
        logger.info("Consumer group created")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info("Consumer group already exists")
        else:
            raise

# ═══════════════════════════════════════════════════════════════════════════════
# BUSINESS LOGIC
# ═══════════════════════════════════════════════════════════════════════════════
def process_note(note: dict) -> None:
    """Idempotent note processing. Replace with real logic."""
    logger.info(
        "Processing note",
        extra={
            "note_id": note.get("note_id"),
            "trace_id": note.get("trace_id"),
            "retry_count": note.get("retry_count"),
        },
    )
    # Simulate work
    time.sleep(0.2)

# ═══════════════════════════════════════════════════════════════════════════════
# NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════════
def _normalize_fields(fields: dict) -> dict:
    retry_count = int(fields.get("retry_count", 0) or 0)

    payload_json = fields.get("payload") or fields.get("data")
    payload = {}
    if payload_json:
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = {}

    note_id = fields.get("note_id") or payload.get("note_id") or payload.get("id")
    trace_id = fields.get("trace_id") or payload.get("trace_id")

    return {
        "event": fields.get("event") or payload.get("event") or "notes.created",
        "note_id": str(note_id) if note_id is not None else None,
        "trace_id": trace_id,
        "retry_count": retry_count,
        "payload": payload_json or json.dumps(payload),
    }

# ═══════════════════════════════════════════════════════════════════════════════
# RETRY QUEUE (ZSET)
# ═══════════════════════════════════════════════════════════════════════════════
_POP_DUE_RETRIES_LUA = """
local zset_key = KEYS[1]
local now_score = ARGV[1]
local limit = tonumber(ARGV[2])
local members = redis.call('ZRANGEBYSCORE', zset_key, '-inf', now_score, 'LIMIT', 0, limit)
if #members > 0 then
  redis.call('ZREM', zset_key, unpack(members))
end
return members
"""


def enqueue_retry(fields: dict, score: float, member: str) -> None:
    r.hset(RETRY_PAYLOAD_HASH_KEY, member, json.dumps(fields))
    r.zadd(RETRY_SCHEDULE_ZSET_KEY, {member: score})


def drain_due_retries(max_items: int = 25) -> int:
    now = time.time()
    members = r.eval(_POP_DUE_RETRIES_LUA, 1, RETRY_SCHEDULE_ZSET_KEY, now, max_items)
    if not members:
        return 0

    payloads = r.hmget(RETRY_PAYLOAD_HASH_KEY, members)
    moved = 0
    for member, payload_json in zip(members, payloads):
        if not payload_json:
            r.hdel(RETRY_PAYLOAD_HASH_KEY, member)
            continue

        try:
            fields = json.loads(payload_json)
            fields = {k: str(v) for k, v in fields.items() if v is not None}
            r.xadd(STREAM_KEY, fields)
            moved += 1
        finally:
            r.hdel(RETRY_PAYLOAD_HASH_KEY, member)

    if moved:
        logger.info("Moved due retries back to stream", extra={"count": moved})
    return moved

# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════════════════════════
def handle_message(message_id: str, fields: dict) -> None:
    normalized = _normalize_fields(fields)
    retry_count = normalized["retry_count"]
    note_id = normalized["note_id"]
    trace_id = normalized.get("trace_id")
    event_type = normalized.get("event") or "notes.created"

    log_extra = {
        "message_id": message_id,
        "note_id": note_id,
        "trace_id": trace_id,
        "retry_count": retry_count,
    }

    # Idempotency
    if note_id is not None and r.sismember(PROCESSED_SET_KEY, note_id):
        logger.info("Duplicate message skipped", extra=log_extra)
        r.xack(STREAM_KEY, GROUP_NAME, message_id)
        return

    start_ms = time.time() * 1000
    try:
        process_note({
            "note_id": note_id,
            "trace_id": trace_id,
            "retry_count": retry_count,
            "payload": normalized.get("payload"),
        })

        duration_ms = time.time() * 1000 - start_ms

        # Record metrics
        MESSAGES_PROCESSED.labels(consumer=CONSUMER_NAME, event_type=event_type).inc()
        PROCESSING_DURATION.labels(consumer=CONSUMER_NAME, event_type=event_type).observe(duration_ms)

        if note_id is not None:
            r.sadd(PROCESSED_SET_KEY, note_id)

        r.xack(STREAM_KEY, GROUP_NAME, message_id)
        logger.info("Message processed", extra={**log_extra, "duration_ms": round(duration_ms, 2)})

    except Exception as e:
        retry_count += 1
        if retry_count <= MAX_RETRIES:
            delay = calculate_backoff(retry_count)
            next_ts = time.time() + delay

            RETRIES_TOTAL.labels(consumer=CONSUMER_NAME).inc()

            logger.warning(
                "Retry scheduled",
                extra={**log_extra, "retry_count": retry_count, "delay_seconds": delay, "error": str(e)},
            )

            retry_fields = {
                "event": event_type,
                "note_id": note_id or "",
                "trace_id": trace_id or "",
                "retry_count": str(retry_count),
                "payload": normalized.get("payload") or "{}",
            }
            enqueue_retry(retry_fields, next_ts, f"{message_id}:{retry_count}")
        else:
            DLQ_TOTAL.labels(consumer=CONSUMER_NAME).inc()
            logger.error("Sending to DLQ", extra=log_extra)
            r.xadd(DLQ_KEY, {
                "original_message_id": message_id,
                "payload": json.dumps(fields),
                "failed_at": datetime.utcnow().isoformat(),
            })

        r.xack(STREAM_KEY, GROUP_NAME, message_id)

# ═══════════════════════════════════════════════════════════════════════════════
# PENDING RECOVERY
# ═══════════════════════════════════════════════════════════════════════════════
def reclaim_stuck_messages() -> None:
    result = r.xautoclaim(
        STREAM_KEY,
        GROUP_NAME,
        CONSUMER_NAME,
        min_idle_time=IDLE_TIME_MS,
        start_id="0-0",
    )
    messages = result[1] if isinstance(result, (list, tuple)) and len(result) >= 2 else []
    for message_id, fields in messages:
        handle_message(message_id, fields)

# ═══════════════════════════════════════════════════════════════════════════════
# BACKOFF
# ═══════════════════════════════════════════════════════════════════════════════
def calculate_backoff(retry_count: int) -> int:
    exponential = min(BASE_DELAY_SEC * (2 ** (retry_count - 1)), MAX_DELAY_SECONDS)
    jitter = random.uniform(0, exponential * 0.25)
    return int(exponential + jitter)

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    connect_to_redis()
    ensure_consumer_group()
    start_health_server()

    logger.info("Worker started")
    touch_health_file()

    while True:
        touch_health_file()
        drain_due_retries()

        streams = r.xreadgroup(GROUP_NAME, CONSUMER_NAME, {STREAM_KEY: ">"}, count=1, block=1000)
        if streams:
            for _, messages in streams:
                for message_id, fields in messages:
                    handle_message(message_id, fields)

        reclaim_stuck_messages()


if __name__ == "__main__":
    main()
