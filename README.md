# Notification Service (FastAPI)

Multi-channel notification service demonstrating template management, queue processing with retries and circuit breaker, scheduling, analytics, and Dockerized deployment.

- Channels: email (SMTP or mock), sms (mock Twilio), webhook (HTTP POST), push (mock)
- Queue: priority-based workers, retries with exponential backoff + jitter, per-recipient circuit breaker, optional rate limiting
- Templates: Jinja2 templates with variables, conditionals, and custom filters
- Scheduler: timezone-aware, cron-based recurrence
- Storage: SQLite (PostgreSQL-compatible schema)
- Analytics: delivery rates, average delivery time, failure breakdown
- Docker: app + Redis (enabled by default)

## Architecture Overview

Components:
- FastAPI app with modular routers:
  - /notifications: send, schedule, batch, status
  - /templates: create, list (pagination and filtering)
  - /analytics: summary metrics
- Queue workers (app/services/queue_service.py):
  - In-memory priority queue keyed by priority + enqueue time
  - Retry plans per priority with exponential backoff + jitter
  - Per-recipient circuit breaker (open/half-open/closed)
  - Optional per-recipient rate limiter (in-memory token bucket)
  - Channel abstraction with implementations for email/sms/webhook/push
- Template service (app/services/template_service.py):
  - CRUD (create/list), render with Jinja2 and filters
- Scheduler service (app/services/scheduler_service.py):
  - Background loop polls DB for due schedules, enqueues notifications
  - Timezone-aware with zoneinfo; cron expressions via croniter
- Database (app/database.py):
  - SQLAlchemy ORM models for notifications, delivery_attempts, templates, scheduled_notifications
  - Indices on recipient, status, created_at, and send_at
- Analytics (app/services/analytics_service.py):
  - Aggregation queries for delivery rates, average delivery time, and failure reasons

Request flow:
1. API receives a request (send or batch). Returns tracking IDs immediately.
2. Queue persists a queued notification and enqueues it in-memory.
3. Workers process the queue, render templates, invoke appropriate channel send, and record attempts.
4. Retry logic applies for transient failures; circuit breaker may fast-fail.
5. Status endpoint reads the persisted status and attempt history.

## Project Structure

notification-service/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   ├── channels/
│   │   ├── base.py
│   │   ├── email_channel.py
│   │   ├── sms_channel.py
│   │   ├── webhook_channel.py
│   │   └── push_channel.py
│   ├── services/
│   │   ├── queue_service.py
│   │   ├── template_service.py
│   │   ├── scheduler_service.py
│   │   └── analytics_service.py
│   ├── api/
│   │   ├── notifications.py
│   │   ├── templates.py
│   │   └── analytics.py
│   └── utils/
│       ├── retry_handler.py
│       └── rate_limiter.py
├── tests/
│   ├── test_channels.py
│   ├── test_queue.py
│   ├── test_templates.py
│   └── test_integration.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── TODO.md

## Setup

### Prerequisites
- Python 3.11+
- Docker and Docker Compose (optional but recommended)
- Windows/Linux/MacOS

### Local (without Docker)
1. Create and activate virtual environment (recommended)
2. Install dependencies
3. Run the app

Commands (Windows CMD/Powershell):
- python -m venv .venv
- .venv\Scripts\activate
- pip install -r requirements.txt
- set HOST=0.0.0.0
- set PORT=8000
- set RELOAD=true
- set DB_DIR=./data
- mkdir data
- python -m app.main

Open http://localhost:8000/docs for Swagger UI.

### Docker

Build and run with Redis enabled by default:
- docker compose up --build

App available at http://localhost:8000

Data (SQLite) stored in ./data volume on the host.

### Environment Variables (.env)

Copy and adjust:
- cp .env.example .env

Key variables:
- HOST, PORT, RELOAD, LOG_LEVEL
- DB_DIR (SQLite data folder)
- REDIS_URL (optional; enabled by default in docker-compose)
- QUEUE_WORKERS (default 4)
- RATE_LIMIT_ENABLED, RATE_LIMIT_CAPACITY, RATE_LIMIT_REFILL
- CB_COOLDOWN (circuit breaker cooldown seconds)
- SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, SMTP_USE_TLS, SMTP_STARTTLS
- ADD_SPF_HEADER, ADD_DKIM_HEADER

Email channel behavior:
- Real SMTP is auto-enabled only when SMTP_* variables are provided. Otherwise the email channel uses mock delivery.


## Database Migrations (Alembic)

This project uses Alembic for schema migrations.

### Initialize (already done in repo)
- alembic init migrations

### Create new migration
- alembic revision --autogenerate -m "description"

### Apply migrations
- alembic upgrade head

### Rollback last migration
- alembic downgrade -1

The migration setup loads the database URL from `.env` if `DATABASE_URL` is set, otherwise it falls back to `alembic.ini`.

Example `.env`:

## API

Base URL: http://localhost:8000

Endpoints:
- POST /notifications/send
- POST /notifications/schedule
- GET /notifications/{tracking_id}/status
- POST /notifications/batch
- POST /templates
- GET /templates
- GET /analytics/summary

Example calls:

Send notification:
curl -X POST "http://localhost:8000/notifications/send" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "email",
    "recipient": "user@example.com",
    "template_id": "welcome-email",
    "variables": {"name": "John", "plan": "Premium"},
    "priority": "high"
  }'

Create template:
curl -X POST "http://localhost:8000/templates" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "order-confirmation",
    "channel": "email",
    "subject": "Order #{{ order_id }} Confirmed",
    "body": "Hello {{ name }}, your order is confirmed!",
    "variables": ["order_id", "name"]
  }'

Check delivery status:
curl "http://localhost:8000/notifications/{tracking_id}/status"

Batch send:
curl -X POST "http://localhost:8000/notifications/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "delivery_mode": "best_effort",
    "notifications": [
      {
        "channel": "sms",
        "recipient": "+15551234567",
        "content": {"body": "Hello from the queue!"},
        "priority": "normal"
      }
    ]
  }'

List templates:
curl "http://localhost:8000/templates?page=1&size=10&channel=email&active=true"

Analytics summary:
curl "http://localhost:8000/analytics/summary"

## Template Syntax

Jinja2 with built-in and custom filters:
- Variables: Hello {{ name }}, order #{{ order_id }}
- Conditionals: {% if premium_user %}Exclusive offer!{% endif %}
- Filters:
  - {{ amount | currency }}  -> $1,234.00
  - {{ date | format_date("%Y-%m-%d") }}

Templates are stored with:
- subject (optional, email-focused)
- body (required)
- variables: required variable names enforced at render time

## Channels

- Email (SMTP or mock)
  - aiosmtplib for async SMTP when SMTP_* env present
  - HTML and plain text parts
  - Attachments up to 10MB (validated via metadata only)
  - SPF/DKIM header placeholders (not actual signing)
- SMS (Mock Twilio)
  - E.164-like validation, simulate 1–5s delay, 5% carrier failures
  - Character limits (1000 hard cap, segment info returned)
- Webhook
  - HTTP POST via httpx with timeout 10s, SSL verify, custom headers
  - Retries handled by queue on transient errors (timeouts, 5xx)
- Push (Mock)
  - Device token validation
  - Simulated receipts and network delays

## Queue, Retries, and Circuit Breaker

- Priority Queue:
  - critical (0), high (1), normal (2), low (3)
- Retry strategy:
  - critical: attempts=5, delays=[1,5,15,60,300]
  - high: attempts=3, delays=[5,30,120]
  - normal: attempts=2, delays=[10,60]
  - low: attempts=1, delays=[]
  - Exponential backoff with jitter fallback beyond configured delays
- Circuit breaker per recipient:
  - Closed → Open after threshold failures
  - Open → Half-open after cooldown, single probe
  - Half-open success → Closed, failure → Open
- Optional rate limiting per recipient using token bucket

## Scheduler

- Stores scheduled notifications with:
  - schedule_id, notification data (same shape as NotificationRequest)
  - send_at (naive stored as UTC), timezone
  - recurrence (cron expression) optional
  - last_run, active
- Background loop polls due schedules, enqueues notifications, and advances next occurrence for recurring schedules.

## Analytics

- by_channel_delivery_rates: delivered/total per channel
- avg_delivery_time_ms: average from creation to delivery
- failure_reasons: breakdown of failure reasons

## Performance Tuning

- Increase QUEUE_WORKERS (e.g., 8, 16) for higher throughput
- Keep SMTP and httpx clients warm (future enhancement: connection pools)
- Ensure DB_DIR is on fast disk; consider PostgreSQL for production
- Reduce logging and payload sizes
- Configure RATE_LIMIT_* to protect recipients
- Use Docker or deploy behind a process manager (e.g., Gunicorn with Uvicorn workers)

Targets:
- Process 100 notifications/second: scale workers and avoid slow channels (mock channels meet this)
- High priority latency < 2s: ensured by worker priority and minimal work per attempt
- API response < 200ms: endpoints return immediately after enqueue
- 1000 concurrent schedules: scheduler loop is O(n) over active schedules; consider indexing and batching for large scale
- Memory < 256MB: avoid large in-memory buffers; use SQLite and batch queries

## Running Tests

- pip install -r requirements.txt
- pytest -q

Tests include:
- Channel success/failure paths with mocked delays
- Template rendering and validation
- Queue processing and retry logic
- Simple integration flow

Load testing (example script provided in tests/load_test.py):
- Start the app (Docker or local)
- Run: python -m tests.load_test
- The script sends 1000 mixed notifications and reports throughput

## Docker

Build and run:
- docker compose up --build

Environment:
- App listens on 0.0.0.0:8000
- Redis enabled by default at redis://redis:6379/0
- SQLite volume mounted at ./data

Healthchecks:
- /healthz for liveness
- /readyz for readiness (basic)

## Notes and Future Work

- Optional Redis-backed persistent queue (current implementation is in-memory with DB persistence of notifications and attempts)
- Webhook signature verification (HMAC) as a bonus
- Prometheus metrics export
- Admin UI for monitoring
- Replace SQLite with PostgreSQL for production scale


