import redis
import json
import time

r = redis.Redis(
    host="redis",
    port=6379,
    decode_responses=True
)

pubsub = r.pubsub()
pubsub.subscribe("notes.created")

print("📡 Notes Processor listening for events...")

for message in pubsub.listen():
    if message["type"] != "message":
        continue

    note = json.loads(message["data"])

    print("📝 New note received")
    print(f"ID: {note['id']}")
    print(f"Title: {note['title']}")
    print(f"Content: {note['content']}")
    print("-" * 40)

    # placeholder for real work:
    # - NLP
    # - analytics
    # - notifications
    time.sleep(0.2)
