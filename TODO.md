# Notification Service - TODO

Status Legend:
- [ ] Not started
- [~] In progress
- [x] Done

## 0) Project Scaffolding
- [x] Create base structure:
  - [x] app/__init__.py (app factory, routers include, startup/shutdown)
  - [x] app/main.py (uvicorn entrypoint, health endpoints)
  - [x] app/models.py (Pydantic schemas per spec)
  - [x] app/database.py (SQLAlchemy engine/session, ORM models, init_db)
  - [x] app/channels/{base.py,email_channel.py,sms_channel.py,webhook_channel.py,push_channel.py}
  - [x] app/services/{queue_service.py,template_service.py,scheduler_service.py,analytics_service.py}
  - [x] app/api/{notifications.py,templates.py,analytics.py}
  - [x] app/utils/{retry_handler.py,rate_limiter.py,logging.py}
  - [x] tests/{test_channels.py,test_queue.py,test_templates.py,test_integration.py,load_test.py}
  - [x] requirements.txt
  - [x] Dockerfile
  - [x] docker-compose.yml
  - [x] README.md
  - [x] .env.example

## 1) Database and ORM (SQLite; PostgreSQL-compatible schema)
- [x] Define ORM models (SQLAlchemy):
  - [x] Notification (tracking_id, channel, recipient, content JSON, status, priority, attempts, created_at, scheduled_for, delivered_at)
  - [x] DeliveryAttempt (id, tracking_id FK, attempt_number, status, error_message, attempted_at, latency_ms)
  - [x] Template (template_id, name unique, channel, content JSON, variables JSON, active, created_at, updated_at)
  - [x] ScheduledNotification (schedule_id, notification_data JSON, send_at, timezone, recurrence, last_run, active)
- [x] Indexes on recipient, status, created_at, send_at
- [x] init_db() create_all on startup
- [x] DB session dependency for FastAPI

## 2) Pydantic Models
- [x] Implement per spec:
  - [x] NotificationRequest
  - [x] NotificationStatus
  - [x] Template (API schema separate from ORM)
  - [x] BatchRequest
  - [x] ScheduledNotification
  - [x] DeliveryAttempt
- [x] Add pagination request/response schemas

## 3) Template Engine (Jinja2)
- [x] Setup Jinja2 environment with custom filters:
  - [x] currency
  - [x] format_date
- [x] TemplateService:
  - [x] Create, list with pagination/filtering, get, activate/deactivate
  - [x] Validate required variables
  - [x] Render subject/body with variables and conditionals
- [x] Persist templates to DB

## 4) Channels Abstraction
- [x] BaseChannel interface and ChannelError
- [x] Channel registry and factory
- [x] Email (aiosmtplib if SMTP_* provided; otherwise mock)
  - [x] HTML/plain text support
  - [x] Attachments up to 10MB (validate size)
  - [x] SPF/DKIM headers placeholder
- [x] SMS (Mock Twilio)
  - [x] Character count validation
  - [x] Simulate delay 1–5s
  - [x] Simulate carrier failures (5%)
- [x] Webhook
  - [x] httpx POST with custom headers
  - [x] Timeout 10s, SSL verify
  - [x] Retries on 5xx/timeout
- [x] Push (Mock)
  - [x] Token validation
  - [x] Mock delivery receipts

## 5) Retry Logic and Rate Limiting
- [x] Retry configs by priority:
  - [x] critical: max 5, delays [1, 5, 15, 60, 300]
  - [x] high: max 3, delays [5, 30, 120]
  - [x] normal: max 2, delays [10, 60]
  - [x] low: max 1, delays []
- [x] Exponential backoff with jitter
- [x] Per-recipient circuit breaker (open/half-open/closed)
- [x] Optional per-recipient rate limiter (token bucket)
- [x] Channel-specific transient error handling

## 6) Queue Management
- [x] In-memory priority queue (heapq): (priority, enqueue_ts, item)
- [x] Background workers:
  - [x] Dispatcher concurrency configurable
  - [x] State transitions: queued → sending → delivered/failed/bounced
  - [x] Persist Notification and DeliveryAttempt
- [x] Batch processing every 10s
- [x] Redis integration (enabled by default via docker-compose):
  - [x] Use list or streams if REDIS_URL set
  - [x] Fallback to in-memory if unavailable
- [x] Circuit breaker & rate limiter integration in sending path

## 7) Scheduler Service
- [x] Create scheduled notifications
- [x] Timezone-aware (zoneinfo)
- [x] Recurrence via croniter
- [x] Background loop to enqueue due notifications
- [x] Update last_run and handle recurrence
- [x] Support pausing via active flag

## 8) API Endpoints
- [x] POST /notifications/send (immediate)
  - [x] Accept single or bulk recipients
  - [x] Return tracking_id
- [x] POST /notifications/schedule
  - [x] Future schedule, recurrence, timezone-aware
  - [x] Return schedule_id
- [x] GET /notifications/{tracking_id}/status
  - [x] Include attempts and failure reasons
- [x] POST /templates
  - [x] Create reusable template (variables and conditionals)
- [x] GET /templates
  - [x] Pagination, filter by channel and active
- [x] POST /notifications/batch
  - [x] Up to 100; atomic or best_effort
  - [x] Return batch_id and individual tracking_ids
- [x] GET /analytics/summary
  - [x] Delivery rates by channel
  - [x] Average delivery time
  - [x] Failure reasons breakdown

## 9) Tests
- [x] Unit tests:
  - [x] Channels: success, failures, retries, template rendering, rate limiting
  - [x] Queue: priority ordering, retries, circuit breaker
  - [x] Templates: variable validation, conditionals, filters
- [x] Integration tests:
  - [x] End-to-end notification flow
  - [x] Batch processing
  - [x] Scheduled notifications
  - [x] Priority queue ordering
- [x] Load test script (tests/load_test.py):
  - [x] Send 1000 notifications (mixed channels/priorities)
  - [x] Measure delivery rates and queue performance

## 10) Docker & Deployment
- [x] requirements.txt
- [x] Dockerfile (multi-stage, non-root, healthcheck)
- [x] docker-compose.yml:
  - [x] App service with environment and volume for SQLite
  - [x] Redis service enabled by default
  - [x] Healthchecks
  - [x] Dev/prod profiles
- [x] .env.example with SMTP_*, REDIS_URL, worker config, etc.

## 11) Documentation
- [x] README.md
  - [x] System architecture overview
  - [x] Setup (local and Docker)
  - [x] Channel configuration guide
  - [x] Template syntax docs
  - [x] API examples for all endpoints
  - [x] Performance tuning guide
  - [x] Load testing instructions

## 12) Performance Validation
- [ ] Tune worker counts and batch sizes
- [ ] Verify:
  - [ ] 100 notifications/second
  - [ ] < 2s latency for high priority
  - [ ] API response time < 200ms
  - [ ] 1000 concurrent scheduled notifications
  - [ ] Memory usage < 256MB

## 13) Bonus
- [x] Real SMTP integration (auto-enable when SMTP_* provided)
- [ ] Webhook signature verification
- [x] Rate limiting per recipient (enable via env)
- [ ] Admin UI for monitoring (optional)
- [ ] Prometheus metrics (optional)
