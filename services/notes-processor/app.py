import redis
import json
import time
import logging
import socket
import random
import os
from datetime import datetime, timedelta
from pythonjsonlogger import jsonlogger

# ─────────────────── Configuration ───────────────────
STREAM_KEY = "notes_stream"
GROUP_NAME = "notes_processors"
CONSUMER_NAME = f"worker-{socket.gethostname()}"
DLQ_KEY = "notes_stream_dlq"
PROCESSED_SET_KEY = "processed_notes"

# Delay queue (retry scheduling)
RETRY_SCHEDULE_ZSET_KEY = "notes_stream_retry_schedule"
RETRY_PAYLOAD_HASH_KEY = "notes_stream_retry_payloads"

MAX_RETRIES = 3
IDLE_TIME_MS = 60000  # reclaim after 60s
BASE_DELAY_SEC = 2 # base delay for retries
MAX_DELAY_SECONDS = 60 # max delay cap

# Healthcheck heartbeat file (used by docker-compose healthcheck)
HEALTH_FILE = "/tmp/healthy"


def touch_health_file() -> None:
    os.makedirs(os.path.dirname(HEALTH_FILE), exist_ok=True)
    with open(HEALTH_FILE, "w", encoding="utf-8") as f:
        f.write(str(time.time()))

# ─────────────────── Logging ───────────────────
logger = logging.getLogger()
handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ─────────────────── Redis Connection ───────────────────
def connect_to_redis():
    while True:
        try:
            client = redis.Redis(host="redis", port=6379, decode_responses=True)
            client.ping()
            logger.info("Connected to Redis")
            return client
        except redis.exceptions.ConnectionError:
            logger.warning("Waiting for Redis...")
            touch_health_file()
            time.sleep(2)

r = connect_to_redis()

# ─────────────────── Consumer Group Setup ───────────────────
def ensure_consumer_group():
    try:
        r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True) ## Create consumer group
        logger.info("Consumer group created")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info("Consumer group already exists")
        else:
            raise

# ─────────────────── Business Logic ───────────────────
def process_note(note):
    """
    This is where real work happens.
    Must be idempotent.
    """
    logger.info(
        "Processing note",
        extra={
            "note_id": note.get("note_id"),
            "trace_id": note.get("trace_id"),
            "retry_count": note.get("retry_count")
        }
    )

    # Simulate work
    time.sleep(0.2)

# ─────────────────── Message Handler ───────────────────
def _normalize_fields(fields: dict) -> dict:
    """Normalize producer payload to a stable stream schema.

    Supported inputs:
    - New schema: fields include note_id/trace_id/retry_count/payload
    - Legacy schema: fields include event + data (JSON)
    """
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
    """Move due retry payloads from ZSET back into the stream.

    Uses a Lua pop to avoid two workers popping the same members.
    """
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
            # Ensure string values in the stream
            fields = {k: str(v) for k, v in fields.items() if v is not None}
            r.xadd(STREAM_KEY, fields)
            moved += 1
        finally:
            r.hdel(RETRY_PAYLOAD_HASH_KEY, member)

    if moved:
        logger.info("Moved due retries back to stream", extra={"count": moved})
    return moved


def handle_message(message_id, fields):
    normalized = _normalize_fields(fields)
    retry_count = normalized["retry_count"]
    note_id = normalized["note_id"]

    # Idempotency check
    if note_id is not None and r.sismember(PROCESSED_SET_KEY, note_id):
        logger.info("Duplicate message skipped", extra={"note_id": note_id})
        r.xack(STREAM_KEY, GROUP_NAME, message_id)
        return

    try:
        process_note({
            "note_id": note_id,
            "trace_id": normalized.get("trace_id"),
            "retry_count": retry_count,
            "payload": normalized.get("payload"),
        })

        # Mark processed
        if note_id is not None:
            r.sadd(PROCESSED_SET_KEY, note_id)

        # ACK on success
        r.xack(STREAM_KEY, GROUP_NAME, message_id)

    except Exception as e:
        retry_count += 1
        ## Log failure
        if retry_count <= MAX_RETRIES:
            delay = calculate_backoff(retry_count)
            next_attempt_ts = time.time() + delay

            logger.warning(
                "Retry scheduled (delay queue)",
                extra={
                    "note_id": note_id,
                    "trace_id": normalized.get("trace_id"),
                    "retry_count": retry_count,
                    "delay_seconds": delay,
                    "error": str(e),
                },
            )

            retry_fields = {
                "event": normalized.get("event") or "notes.created",
                "note_id": note_id or "",
                "trace_id": normalized.get("trace_id") or "",
                "retry_count": str(retry_count),
                "payload": normalized.get("payload") or "{}",
            }

            member = f"{message_id}:{retry_count}"
            enqueue_retry(retry_fields, next_attempt_ts, member)

        else:
            logger.error("Sending to DLQ", extra={"note_id": note_id})
            ## Send to DLQ
            r.xadd(DLQ_KEY, {
                "original_message_id": message_id,
                "payload": json.dumps(fields),
                "failed_at": datetime.utcnow().isoformat()
            })

        # ACK the original message
        r.xack(STREAM_KEY, GROUP_NAME, message_id)


# ─────────────────── Pending Recovery ───────────────────
def reclaim_stuck_messages():
    ## Claim messages idle for more than IDLE_TIME_MS
    result = r.xautoclaim(
        STREAM_KEY,
        GROUP_NAME,
        CONSUMER_NAME,
        min_idle_time=IDLE_TIME_MS,
        start_id="0-0"
    )

    # redis-py may return (next_start_id, messages) or (next_start_id, messages, deleted_ids)
    if isinstance(result, (list, tuple)) and len(result) >= 2:
        messages = result[1]
    else:
        messages = []
    ## Process reclaimed messages
    for message_id, fields in messages:
        handle_message(message_id, fields)

# --------------Helper functoins for exponential backoff--------------
def calculate_backoff(retry_count: int) -> int:
    """
    Exponential backoff with jitter.
    retry_count starts at 1.
    """
    ## Calculate exponential delay
    exponential = min(
        BASE_DELAY_SEC * (2 ** (retry_count - 1)),
        MAX_DELAY_SECONDS
    )

    ## Add jitter (0% to 25% of exponential)
    jitter = random.uniform(0, exponential * 0.25)

    # Return total delay
    return int(exponential + jitter)


# ─────────────────── Main Loop ───────────────────
def main():
    # Setup consumer group
    ensure_consumer_group()
    logger.info(f"Worker started: {CONSUMER_NAME}")

    touch_health_file()

    ## Main processing loop
    while True:
        touch_health_file()

        # Move due delayed retries back into the main stream.
        drain_due_retries()

        ## Read messages
        streams = r.xreadgroup(
            GROUP_NAME,
            CONSUMER_NAME,
            {STREAM_KEY: ">"},
            count=1,
            block=1000
        )
        ## Process messages
        if streams:
            for _, messages in streams:
                for message_id, fields in messages:
                    handle_message(message_id, fields)
        ## Reclaim stuck messages
        reclaim_stuck_messages()


# ─────────────────── Entry Point ───────────────────
if __name__ == "__main__":
    main()
