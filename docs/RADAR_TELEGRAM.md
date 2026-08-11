# R4D Telegram Delivery

## Purpose

R4D adds an optional outbound Telegram adapter to EIS Procurement Radar. The adapter sends only alerts already produced by the R4C `alert_feed`; it does not repeat technical scoring, opportunity logic, or alert filtering.

Current Radar milestone: `0.4.3-r4d-telegram-delivery`.

## Configuration

Telegram delivery is disabled by default in `config/radar.example.yaml`.

Preferred credential sources are environment variables:

```text
RADAR_TELEGRAM_BOT_TOKEN
RADAR_TELEGRAM_CHAT_ID
```

The configuration also exposes timeout, retry/backoff, API base URL, and maximum message length. Empty config fields are placeholders only. Real bot tokens and chat IDs must not be committed.

## Delivery flow

```text
alert_feed
    -> Telegram formatter
    -> safe message splitting
    -> duplicate check
    -> HTTPS sendMessage
    -> chunk delivery persistence
    -> alert delivery persistence
```

Each message is derived from an existing alert and can include priority, alert type, procurement number, reason, score/decision, and relevant value changes.

## Persistence and idempotency

SQLite stores alert-level attempts in `alert_delivery_attempts`.

A completed delivery is identified by:

- alert fingerprint;
- channel;
- chat destination.

Once an alert is successfully delivered to that destination, a later attempt is returned as `SKIPPED_DUPLICATE` and no HTTP request is made.

Failed attempts do not block later retries.

## Multi-part messages

Long messages are split below the configured Telegram payload limit. Chunk state is persisted separately in `alert_delivery_chunks`.

This is important for partial failures. If chunk 1 is delivered successfully but chunk 2 fails:

1. the alert remains `FAILED`;
2. chunk 1 remains recorded as `SENT`;
3. the next retry skips chunk 1;
4. only failed or never-attempted chunks are sent;
5. the alert becomes `SENT` only when all chunks have succeeded.

This prevents duplicate partial notifications during transient network failures.

## Retry behavior

Transient HTTP/server and network failures use bounded retries with short backoff.

Permanent HTTP 4xx responses stop retries for the current delivery attempt. They are still recorded as failed rather than marked as successfully delivered, so a later corrected run can retry.

Delivery status values include:

- `SENT`;
- `FAILED`;
- `SKIPPED_DUPLICATE`.

## Failure isolation

Telegram delivery is downstream from Radar analysis and alert generation. A Telegram failure does not invalidate procurement state, change-feed state, alert history, or the last successful published Radar result.

This keeps outbound notification problems separate from analytical correctness.

## CLI

Use the current CLI help as the source of truth:

```powershell
.\.venv\Scripts\python.exe -m radar.runner --help
```

R4D includes explicit Telegram enable/disable controls and optional runtime token/chat overrides. Environment variables remain the preferred production credential source.

## Validation

R4D was accepted with `168 passed` in the complete local test suite.

Mocked tests cover:

- successful send;
- duplicate suppression;
- failed send remaining retryable;
- transient retry followed by success;
- message splitting;
- disabled delivery producing no requests;
- partial multi-chunk failure and retry without resending delivered chunks.

No real Telegram credentials or live delivery are required for the regression suite.

## Security

Do not place real bot tokens, chat IDs, Telegram responses containing sensitive data, or machine-specific production configuration in the repository.

Runtime databases and generated outputs remain local and are excluded from Git.

## Next operational step

The next milestone is production handoff rather than another analytical feature: define a stable recurring run profile, environment setup, startup validation, Windows Task Scheduler invocation, and one controlled real end-to-end run through the Telegram adapter.
