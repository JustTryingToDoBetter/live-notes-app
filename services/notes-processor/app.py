import redis
import json
import time

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
            print("✅ Connected to Redis")
            return r
        except redis.exceptions.ConnectionError:
            print(f"⏳ Waiting for Redis... (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)
    raise Exception("❌ Could not connect to Redis after max retries")

r = connect_to_redis()

pubsub = r.pubsub()
pubsub.subscribe("notes.created")

print("📡 Notes Processor listening for events...")

for message in pubsub.listen():
    if message["type"] != "message":
        continue

    print(f"📥 Received raw message: {message}")

    try:
        note = json.loads(message["data"])
        print("📝 New note received")
        print(f"ID: {note['id']}")
        print(f"Title: {note['title']}")
        print(f"Content: {note['content']}")
        print("-" * 40)
    except json.JSONDecodeError as e:
        print(f"❌ Error decoding JSON: {e}")
        print(f"Raw data: {message['data']}")
    except Exception as e:
        print(f"❌ Error processing message: {e}")

    # placeholder for real work:
    # - NLP
    # - analytics
    # - notifications
    time.sleep(0.2)
