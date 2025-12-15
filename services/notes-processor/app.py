import redis
import json
import time
import logging
import socket
import random
from datetime import datetime, timedelta
from pythonjsonlogger import jsonlogger

# ─────────────────── Configuration ───────────────────
STREAM_KEY = "notes_stream"
GROUP_NAME = "notes_processors"
CONSUMER_NAME = f"worker-{socket.gethostname()}"
DLQ_KEY = "notes_stream_dlq"
PROCESSED_SET_KEY = "processed_notes"

MAX_RETRIES = 3
IDLE_TIME_MS = 60000  # reclaim after 60s
BASE_DELAY_SEC = 2 # base delay for retries
MAX_DELAY_SECONDS = 60 # max delay cap

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
            time.sleep(2)

r = connect_to_redis()

# ─────────────────── Consumer Group Setup ───────────────────
def ensure_consumer_group():
    try:
        r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
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
            "note_id": note["note_id"],
            "trace_id": note.get("trace_id"),
            "retry_count": note.get("retry_count")
        }
    )

    # Simulate work
    time.sleep(0.2)

# ─────────────────── Message Handler ───────────────────
def handle_message(message_id, fields):
    retry_count = int(fields.get("retry_count", 0))
    note_id = fields.get("note_id")

    # time-based rety gate
    next_attempt_time = fields.get("next_attempt_time")
    if next_attempt_time:
        next_attempt_time = datetime.fromisoformat(next_attempt_time)
        if datetime.utcnow() < next_attempt_time:
            # Not yet time to retry, requeue without ACK
            return

    # Idempotency check
    if r.sismember(PROCESSED_SET_KEY, note_id):
        logger.info("Duplicate message skipped", extra={"note_id": note_id})
        r.xack(STREAM_KEY, GROUP_NAME, message_id)
        return

    try:
        process_note(fields)

        # Mark processed
        r.sadd(PROCESSED_SET_KEY, note_id)

        # ACK on success
        r.xack(STREAM_KEY, GROUP_NAME, message_id)

    except Exception as e:
        retry_count += 1

        if retry_count < MAX_RETRIES:
            delay = calculate_backoff(retry_count)
            next_attempt = datetime.utcnow() + timedelta(seconds=delay)

            logger.warning(
                "Retry scheduled",
                extra={
                    "note_id": note_id,
                    "retry_count": retry_count,
                    "delay_seconds": delay
                }
            )

            r.xadd(STREAM_KEY, {
                **fields,
                "retry_count": retry_count,
                "next_attempt_at": next_attempt.isoformat()
            })

        else:
            logger.error("Sending to DLQ", extra={"note_id": note_id})

            r.xadd(DLQ_KEY, {
                "original_message_id": message_id,
                "payload": json.dumps(fields),
                "failed_at": datetime.utcnow().isoformat()
            })

        # ACK the original message
        r.xack(STREAM_KEY, GROUP_NAME, message_id)


# ─────────────────── Pending Recovery ───────────────────
def reclaim_stuck_messages():
    _, messages = r.xautoclaim(
        STREAM_KEY,
        GROUP_NAME,
        CONSUMER_NAME,
        min_idle_time=IDLE_TIME_MS,
        start_id="0-0"
    )

    for message_id, fields in messages:
        handle_message(message_id, fields)

# --------------Helper functoins for exponential backoff--------------
def calculate_backoff(retry_count: int) -> int:
    """
    Exponential backoff with jitter.
    retry_count starts at 1.
    """
    exponential = min(
        BASE_DELAY_SEC * (2 ** (retry_count - 1)),
        MAX_DELAY_SECONDS
    )

    jitter = random.uniform(0, exponential * 0.25)

    return int(exponential + jitter)


# ─────────────────── Main Loop ───────────────────
def main():
    ensure_consumer_group()
    logger.info(f"Worker started: {CONSUMER_NAME}")

    while True:
        streams = r.xreadgroup(
            GROUP_NAME,
            CONSUMER_NAME,
            {STREAM_KEY: ">"},
            count=1,
            block=1000
        )

        if streams:
            for _, messages in streams:
                for message_id, fields in messages:
                    handle_message(message_id, fields)

        reclaim_stuck_messages()



if __name__ == "__main__":
    main()
