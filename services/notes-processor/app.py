import redis
import json
import time
import logging
from pythonjsonlogger import jsonlogger
import os

# Configure JSON logging
logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s')
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# Health check file
HEALTH_FILE = "/tmp/healthy"

def touch_health_file():
    with open(HEALTH_FILE, 'w') as f:
        f.write(str(time.time()))

def connect_to_redis(max_retries=30, delay=2):
    """Connect to Redis with retry logic"""
    for attempt in range(max_retries):
        try:
            r = redis.Redis(
                host="redis",
                port=6379,
                decode_responses=True
            )
            r.ping()  # Test connection
            logger.info("Connected to Redis", extra={"attempt": attempt + 1})
            return r
        except redis.exceptions.ConnectionError:
            logger.warning("Waiting for Redis...", extra={"attempt": attempt + 1, "max_retries": max_retries})
            time.sleep(delay)
    
    logger.error("Could not connect to Redis after max retries")
    raise Exception("Could not connect to Redis after max retries")

r = connect_to_redis()

pubsub = r.pubsub()
pubsub.subscribe("notes.created")

logger.info("Notes Processor listening for events...")

# Initial health touch
touch_health_file()

for message in pubsub.listen():
    # Update health status on every loop iteration
    touch_health_file()

    if message["type"] != "message":
        continue

    logger.info("Received raw message", extra={"message_data": message})

    try:
        note = json.loads(message["data"])
        logger.info("New note received", extra={
            "note_id": note.get('id'),
            "note_title": note.get('title')
        })
    except json.JSONDecodeError as e:
        logger.error("Error decoding JSON", extra={"error": str(e), "raw_data": message['data']})
    except Exception as e:
        logger.error("Error processing message", extra={"error": str(e)})

    # placeholder for real work:
    # - NLP
    # - analytics
    # - notifications
    time.sleep(0.2)
