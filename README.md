# Live Notes App

A production-grade real-time notes application demonstrating modern distributed systems patterns with Laravel, React, Redis Streams, and Python workers.

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                   CLIENTS                                        │
│                         (React SPA with SSE Connection)                          │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              NGINX (Reverse Proxy)                               │
│  • Static file serving (React dist)                                              │
│  • FastCGI proxy to PHP-FPM                                                      │
│  • SSE endpoint with disabled buffering                                          │
│  • Health check endpoint (/health)                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                      ▼
┌─────────────────────────────────┐    ┌─────────────────────────────────────────┐
│       Laravel API (PHP-FPM)      │    │           Notes Processor (Python)       │
│  • REST API (/api/notes)         │    │  • Redis Streams consumer (XREADGROUP)   │
│  • SSE endpoint (/api/events)    │    │  • Exactly-once processing               │
│  • Redis Stream producer (XADD)  │    │  • ZSET-based retry queue                │
│  • Pub/Sub subscriber for SSE    │    │  • Dead-letter queue (DLQ)               │
│  • Response caching              │    │  • Prometheus metrics (/metrics)         │
└─────────────────────────────────┘    │  • Health endpoint (/health)             │
                    │                   └─────────────────────────────────────────┘
                    │                                      │
                    └──────────────────┬───────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                REDIS 7                                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐  │
│  │  notes_stream   │  │  notes_events   │  │  notes_stream_retry_schedule    │  │
│  │  (Redis Stream) │  │  (Pub/Sub)      │  │  (ZSET - Delay Queue)           │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐  │
│  │ processed_notes │  │ notes_stream_dlq│  │  notes_stream_retry_payloads    │  │
│  │ (SET-Idempotent)│  │ (Dead Letter Q) │  │  (HASH - Retry Payloads)        │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              SQLite / MySQL                                      │
│                           (Persistent Storage)                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## 🔄 Data Flow

### 1. Note Creation Flow
```
User → React App → POST /api/notes → Laravel Controller
                                          │
                                          ├─→ Save to Database
                                          ├─→ Invalidate Cache
                                          └─→ XADD to notes_stream
                                                    │
                                                    ▼
                                          Python Worker (XREADGROUP)
                                                    │
                                          ├─→ Process Note (business logic)
                                          ├─→ XACK (acknowledge)
                                          ├─→ Add to processed_notes SET
                                          └─→ PUBLISH to notes_events
                                                    │
                                                    ▼
                                          Laravel SSE Endpoint
                                                    │
                                                    ▼
                                          React App (EventSource)
                                                    │
                                                    ▼
                                          UI Update (real-time)
```

### 2. Retry Flow (on failure)
```
Worker Processing Error
        │
        ▼
  retry_count < MAX_RETRIES?
        │
   ┌────┴────┐
   │ YES     │ NO
   ▼         ▼
ZADD to     XADD to
retry_schedule   DLQ
   │
   ▼
(wait for delay)
   │
   ▼
Lua script pops due items
   │
   ▼
XADD back to notes_stream
```

## 📁 Project Structure

```
live-notes-app/
├── backend/
│   └── api/                      # Laravel 11 API
│       ├── app/
│       │   ├── Http/Controllers/
│       │   │   ├── NoteController.php      # REST endpoints
│       │   │   └── EventStreamController.php # SSE endpoint
│       │   └── Models/
│       │       └── Note.php
│       ├── config/
│       │   └── database.php      # Redis (phpredis) config
│       ├── routes/
│       │   └── api.php           # API routes
│       └── .env                  # Environment config
│
├── frontend/
│   └── notes-ui/                 # React 19 + Vite
│       └── src/
│           ├── App.jsx           # Main component with SSE
│           └── hooks/
│               └── useEventSource.js  # SSE hook with reconnect
│
├── services/
│   └── notes-processor/          # Python 3.11 worker
│       ├── app.py                # Main worker code
│       ├── requirements.txt
│       └── Dockerfile
│
├── nginx/
│   └── default.conf              # Nginx config with SSE support
│
├── docker/
│   └── docker-compose.prod.yml   # Production Docker Compose
│
└── README.md
```

## 🚀 Getting Started

### Prerequisites

- Docker & Docker Compose
- Node.js 18+ (for local frontend development)
- PHP 8.3+ with phpredis extension (for local backend development)

### Quick Start (Docker)

1. **Clone the repository**
   ```bash
   git clone https://github.com/YourOrg/live-notes-app.git
   cd live-notes-app
   ```

2. **Configure environment**
   ```bash
   cp backend/api/.env.example backend/api/.env
   ```
   
   Ensure these settings in `.env`:
   ```env
   DB_CONNECTION=sqlite
   REDIS_HOST=redis
   REDIS_CLIENT=phpredis
   CACHE_DRIVER=redis
   LOG_CHANNEL=stderr_json
   ```

3. **Build and start all services**
   ```bash
   cd docker
   docker compose -f docker-compose.prod.yml up -d --build
   ```

4. **Run database migrations**
   ```bash
   docker compose -f docker-compose.prod.yml exec app php artisan migrate
   ```

5. **Build the frontend**
   ```bash
   cd ../frontend/notes-ui
   npm install
   npm run build
   ```

6. **Access the application**
   - **Frontend**: http://localhost:8000
   - **API**: http://localhost:8000/api/notes
   - **Worker Metrics**: http://localhost:9090/metrics
   - **Worker Health**: http://localhost:9090/health

### Verify Everything Works

```bash
# Check all containers are healthy
docker compose -f docker-compose.prod.yml ps

# Create a test note
curl -X POST http://localhost:8000/api/notes \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello World","content":"Testing the stack"}'

# Check worker processed it
docker logs docker-notes-processor-1 --tail 10

# Check metrics
curl -s http://localhost:9090/metrics | grep messages_processed
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_HOST` | Redis server hostname | `redis` |
| `REDIS_PORT` | Redis server port | `6379` |
| `REDIS_CLIENT` | Redis PHP client | `phpredis` |
| `LOG_CHANNEL` | Laravel log channel | `stderr_json` |
| `HEALTH_PORT` | Worker health endpoint port | `8080` |

### Worker Configuration (app.py)

| Constant | Description | Default |
|----------|-------------|---------|
| `MAX_RETRIES` | Max retry attempts before DLQ | `3` |
| `BASE_DELAY_SEC` | Base delay for exponential backoff | `2` |
| `MAX_DELAY_SECONDS` | Maximum retry delay | `60` |
| `IDLE_TIME_MS` | Time before reclaiming stuck messages | `60000` |

## 📊 Observability

### Prometheus Metrics (Port 9090)

| Metric | Type | Description |
|--------|------|-------------|
| `messages_processed_total` | Counter | Successfully processed messages |
| `retries_total` | Counter | Retries scheduled |
| `dlq_total` | Counter | Messages sent to DLQ |
| `processing_duration_ms` | Histogram | Processing time in milliseconds |
| `consumer_lag` | Gauge | Pending messages in consumer group |
| `redis_connected` | Gauge | Redis connection status (1/0) |

### Structured Logging

All services emit JSON logs with correlation IDs:

```json
{
  "message": "Message processed",
  "message_id": "1765917711810-0",
  "note_id": "13",
  "trace_id": "2f2f75fd-beb4-4525-9d83-edc79f7ae189",
  "duration_ms": 200.28,
  "consumer": "worker-d081b9bd6f1b"
}
```

### Health Endpoints

| Endpoint | Service | Description |
|----------|---------|-------------|
| `GET /health` | Nginx | Always returns 200 |
| `GET /up` | Laravel | Laravel health check |
| `GET :9090/health` | Worker | Redis connectivity + consumer lag |
| `GET :9090/metrics` | Worker | Prometheus metrics |

## 🔒 Production Considerations

### Security
- Redis port (6379) is not exposed externally
- All internal communication via Docker network
- CORS configured for SSE endpoint

### Reliability
- Exactly-once message processing via idempotency SET
- Exponential backoff with jitter for retries
- Dead-letter queue for failed messages
- Automatic reclamation of stuck messages (XAUTOCLAIM)
- Docker healthchecks for all services

### Scalability
- Stateless workers can be horizontally scaled
- Redis Streams consumer groups for parallel processing
- Response caching with automatic invalidation

## 🧪 Development

### Local Backend Development
```bash
cd backend/api
composer install
php artisan serve
```

### Local Frontend Development
```bash
cd frontend/notes-ui
npm install
npm run dev
```

### Run Tests
```bash
cd backend/api
php artisan test
```

## 📝 API Reference

### Notes

#### List Notes
```
GET /api/notes
```
Response: `200 OK`
```json
[
  {"id": 1, "title": "Note 1", "content": "Content...", "created_at": "..."}
]
```

#### Create Note
```
POST /api/notes
Content-Type: application/json

{"title": "My Note", "content": "Note content"}
```
Response: `201 Created`
```json
{"id": 1, "title": "My Note", "content": "Note content", "created_at": "..."}
```

### Server-Sent Events
```
GET /api/events
Accept: text/event-stream
```
Events:
- `connected` - Initial connection confirmation
- `notes.created` - New note processed
- `notes.updated` - Note updated
- `notes.deleted` - Note deleted

## 🛠️ Troubleshooting

### Worker not processing messages
```bash
# Check Redis Stream
docker exec live-notes-redis redis-cli XINFO STREAM notes_stream

# Check consumer group
docker exec live-notes-redis redis-cli XINFO GROUPS notes_stream

# Check pending messages
docker exec live-notes-redis redis-cli XPENDING notes_stream notes_processors
```

### SSE not connecting
```bash
# Test SSE endpoint directly
curl -N http://localhost:8000/api/events

# Check Nginx logs
docker logs live-notes-nginx --tail 20
```

### Clear stuck state
```bash
# Clear processed messages (allows reprocessing)
docker exec live-notes-redis redis-cli DEL processed_notes

# Clear retry queue
docker exec live-notes-redis redis-cli DEL notes_stream_retry_schedule
docker exec live-notes-redis redis-cli DEL notes_stream_retry_payloads
```

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.
