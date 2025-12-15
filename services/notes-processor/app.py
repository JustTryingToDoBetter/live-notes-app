import redis
import json
import time
import logging
import socket
from pythonjsonlogger import jsonlogger

# --- Configuration ---
STREAM_KEY = "notes_stream"
GROUP_NAME = "notes_processors"
CONSUMER_NAME = f"worker-{socket.gethostname()}"
DLQ_KEY = "notes_dlq"
PROCESSED_SET_KEY = "processed_notes"
MAX_RETRIES = 3
IDLE_TIME_MS = 10000  # 10 seconds

# --- Logging Setup ---
logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s')
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# --- Health Check ---
HEALTH_FILE = "/tmp/healthy"

def touch_health_file():
    with open(HEALTH_FILE, 'w') as f:
        f.write(str(time.time()))

def connect_to_redis():
    """Connect to Redis with retry logic"""
    while True:
        try:
            r = redis.Redis(host="redis", port=6379, decode_responses=True)
            r.ping()
            logger.info("Connected to Redis")
            return r
        except redis.exceptions.ConnectionError:
            logger.warning("Waiting for Redis...")
            time.sleep(2)

r = connect_to_redis()

def ensure_consumer_group():
    """Create the consumer group if it doesn't exist"""
    try:
        r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
        logger.info(f"Created consumer group: {GROUP_NAME}")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"Consumer group {GROUP_NAME} already exists")
        else:
            raise e

def process_message(message_id, message_data):
    """Process a single message with idempotency and error handling"""
    try:
        # 1. Extract Data
        payload_json = message_data.get("data")
        if not payload_json:
            logger.error("Missing data field", extra={"msg_id": message_id})
            return True # Ack invalid messages to remove them

        note = json.loads(payload_json)
        note_id = note.get("id")
        
        # 2. Idempotency Check
        if r.sismember(PROCESSED_SET_KEY, note_id):
            logger.info("Skipping duplicate note", extra={"note_id": note_id})
            return True

        # 3. Business Logic (Simulated)
        logger.info("Processing note", extra={
            "note_id": note_id,
            "title": note.get("title"),
            "stream_id": message_id
        })
        
        # Simulate processing time
        time.sleep(0.2)

        # 4. Mark as Processed
        r.sadd(PROCESSED_SET_KEY, note_id)
        return True

    except json.JSONDecodeError:
        logger.error("Invalid JSON", extra={"msg_id": message_id})
        return True # Ack malformed data
    except Exception as e:
        logger.error("Processing failed", extra={"error": str(e), "msg_id": message_id})
        return False # Do NOT ack, let it go to pending

def handle_pending_messages():
    """Check for stuck messages and retry or DLQ them"""
    try:
        # Fetch detailed pending info
        # Start from minimum ID, count 10
        pending_details = r.xpending_range(STREAM_KEY, GROUP_NAME, "-", "+", 10)
        
        for msg in pending_details:
            msg_id = msg["message_id"]
            idle_time = msg["time_since_delivered"]
            delivery_count = msg["times_delivered"]
            
            if idle_time > IDLE_TIME_MS:
                # Message is stuck
                if delivery_count > MAX_RETRIES:
                    # Move to DLQ
                    logger.error("Moving message to DLQ", extra={"msg_id": msg_id, "retries": delivery_count})
                    
                    # Claim it first to get the data
                    claimed = r.xclaim(STREAM_KEY, GROUP_NAME, CONSUMER_NAME, IDLE_TIME_MS, [msg_id])
                    if claimed:
                        data = claimed[0][1]
                        r.xadd(DLQ_KEY, data)
                        r.xack(STREAM_KEY, GROUP_NAME, msg_id)
                        r.xdel(STREAM_KEY, msg_id)
                else:
                    # Retry (Claim ownership)
                    logger.info("Retrying stuck message", extra={"msg_id": msg_id, "attempt": delivery_count})
                    r.xclaim(STREAM_KEY, GROUP_NAME, CONSUMER_NAME, IDLE_TIME_MS, [msg_id])
                    
    except Exception as e:
        logger.error("Error in recovery loop", extra={"error": str(e)})

def main():
    ensure_consumer_group()
    logger.info(f"Worker {CONSUMER_NAME} started")
    
    while True:
        touch_health_file()
        
        # 1. Read new messages
        # Block for 1 second, read new messages (">")
        streams = r.xreadgroup(GROUP_NAME, CONSUMER_NAME, {STREAM_KEY: ">"}, count=1, block=1000)
        
        if streams:
            for stream, messages in streams:
                for message_id, message_data in messages:
                    success = process_message(message_id, message_data)
                    if success:
                        r.xack(STREAM_KEY, GROUP_NAME, message_id)
                        logger.info("Message acknowledged", extra={"msg_id": message_id})
        
        # 2. Periodic Recovery (Simple implementation: run every loop or use a timer)
        # For high throughput, run this in a separate thread or less frequently
        handle_pending_messages()

if __name__ == "__main__":
    main()
