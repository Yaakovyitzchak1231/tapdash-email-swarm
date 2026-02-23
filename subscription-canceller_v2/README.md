# Subscription Canceller v2

AI browser automation service for cancelling subscriptions with strict intent guardrails. The service exposes an HTTP API (`POST /v1/cancel-subscription`) and uses Playwright to navigate provider pages safely.

## What this service does

- Automates provider login/account/subscription flows using Playwright
- Applies allowlist/denylist guardrails before clicking actions
- Returns structured action logs, outcome metadata, and error codes
- Supports API key protection for the cancellation endpoint

## Project setup

### Prerequisites

- Node.js 18+ (Node 20 recommended)
- npm 9+
- Playwright browser runtime

### 1. Install dependencies

```bash
npm install
```

### 2. Configure environment

```bash
cp .env.example .env
```

Required env vars:

- `OPENAI_API_KEY` (required by config validation)

Common env vars:

- `PORT` (default `3000`)
- `API_KEY` (optional; enables API auth)
- `LOG_LEVEL` (`fatal|error|warn|info|debug|trace`)
- `PLAYWRIGHT_HEADLESS` (`true`/`false`)
- `PLAYWRIGHT_TIMEOUT_MS` (browser timeout override)
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` (for custom Chromium path)

### 3. Build and run

Development:

```bash
npm run dev
```

Production build:

```bash
npm run build
npm start
```

### 4. Verify service

```bash
curl http://localhost:3000/health
```

Expected shape:

```json
{
  "status": "healthy",
  "timestamp": "2026-02-23T00:00:00.000Z",
  "version": "1.0.0"
}
```

## API docs

Base URL: `http://localhost:3000`

### Authentication

If `API_KEY` is set, `POST /v1/cancel-subscription` requires either:

- Header `x-api-key: <API_KEY>`
- Header `authorization: Bearer <API_KEY>`

If `API_KEY` is not set, the endpoint is open.

### `POST /v1/cancel-subscription`

Cancels a user subscription while enforcing guardrails.

#### Request body

```json
{
  "requestId": "7f2f6d83-4f62-45a9-a73b-8120d8a3e63e",
  "mode": "live",
  "provider": {
    "id": "netflix",
    "name": "Netflix"
  },
  "targetUrls": {
    "login": "https://www.netflix.com/login",
    "account": "https://www.netflix.com/YourAccount",
    "subscription": null
  },
  "userSession": {
    "cookies": [
      {
        "name": "sessionid",
        "value": "abc123",
        "domain": ".netflix.com",
        "path": "/",
        "httpOnly": true,
        "secure": true,
        "sameSite": "Lax"
      }
    ],
    "headers": {
      "User-Agent": "Mozilla/5.0 ..."
    }
  },
  "guardrails": {
    "allowedIntents": ["cancel", "unsubscribe", "end membership"],
    "forbiddenIntents": ["update payment method", "change plan", "upgrade"]
  },
  "options": {
    "maxSteps": 40,
    "maxDurationSeconds": 300,
    "dryRun": false
  }
}
```

#### Validation rules

- `requestId`: required UUID
- `provider.id` and `provider.name`: required
- `targetUrls`: at least one of `login|account|subscription` required
- At least one of `userSession` or `credentials` is required
- `guardrails.allowedIntents`: non-empty array
- `options.maxSteps`: max `100`
- `options.maxDurationSeconds`: max `600`

#### Success response (`200`)

```json
{
  "requestId": "7f2f6d83-4f62-45a9-a73b-8120d8a3e63e",
  "status": "success",
  "summary": "Successfully cancelled Netflix subscription",
  "provider": { "id": "netflix", "name": "Netflix" },
  "outcome": {
    "finalUrl": "https://provider.example/cancel/confirmation",
    "cancelConfirmationText": "Your membership has been cancelled.",
    "cancelledAt": "2026-02-23T00:00:00.000Z"
  },
  "actions": [
    {
      "step": 1,
      "type": "navigate",
      "description": "Navigated to https://provider.example/account",
      "timestamp": "2026-02-23T00:00:00.000Z"
    }
  ],
  "logsRef": {
    "id": "7f2f6d83-4f62-45a9-a73b-8120d8a3e63e",
    "location": "internal-logging-system://ai-browser/cancel-subscription/7f2f6d83-4f62-45a9-a73b-8120d8a3e63e"
  }
}
```

#### Other status values

- `no-safe-cancel`: No allowed cancellation path found within guardrails
- `error`: Request failed (timeout, login failure, navigation issue, unexpected error)

#### Error response examples

Validation (`400`):

```json
{
  "requestId": "unknown",
  "status": "error",
  "summary": "Invalid request payload",
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Request validation failed",
    "details": "requestId: Invalid uuid"
  }
}
```

Unauthorized (`401`):

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Invalid or missing API key"
  }
}
```

Not found (`404`):

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Endpoint GET /missing not found"
  }
}
```

### Error codes used by the service

- `INVALID_REQUEST`
- `BROWSER_LAUNCH_FAILED`
- `NAVIGATION_FAILED`
- `LOGIN_FAILED`
- `ELEMENT_NOT_FOUND`
- `INTENT_FORBIDDEN`
- `TIMEOUT`
- `NETWORK_ERROR`
- `UNEXPECTED_ERROR`
- `NO_CANCEL_PATH`
- `GUARDRAIL_VIOLATION`

## Docker instructions

### Build image

```bash
docker build -t subscription-canceller .
```

### Run container

```bash
docker run --rm -p 3000:3000 --env-file .env subscription-canceller
```

### Run with Docker Compose

```bash
docker compose up --build
```

### Important runtime note

Current `Dockerfile` command is `node index.js`, but the TypeScript build outputs `dist/index.js`. Use one of these approaches:

1. Build and include `dist` before image build, then change container command to `node dist/index.js`.
2. Update the `Dockerfile` command to:

```dockerfile
CMD ["node", "dist/index.js"]

## Testing strategy

Unit tests (fast, deterministic):

```bash
npm run test:unit
```

Live smoke tests (real Chromium, no Playwright mocks):

```bash
LIVE_TESTS=true npm run test:live
```

Run both:

```bash
npm run test:all
```

Live test environment variables:

- `LIVE_TESTS` set to `true` to enable live tests (otherwise they are skipped)
- `LIVE_TEST_BASE_URL` target URL for smoke navigation (default `https://example.com/account`)
- `LIVE_TEST_EXPECTED_STATUS` optional strict status assertion (for example `no-safe-cancel`)
- `LIVE_ARTIFACT_DIR` output directory for JSON artifacts (default `artifacts/live-tests`)

CI automation:

- `.github/workflows/subscription-canceller-tests.yml` runs unit tests on PRs and pushes to `master`
- The same workflow runs live tests on `master`, every 30 minutes, and on manual dispatch
- Live test artifacts are uploaded for debugging on success/failure
```

## Provider configuration guide

Provider metadata lives in `src/providers/index.ts` as:

- `providerConfigs`: provider definitions
- `supportedProviders`: provider IDs derived from config keys

Each provider uses:

```ts
interface ProviderConfig {
  name: string;
  loginUrl: string;
  cancelSelectors: string[];
}
```

### Built-in providers

- `netflix`
- `spotify`
- `amazonPrime`
- `youtubePremium`

### Add a new provider

1. Edit `src/providers/index.ts`.
2. Add a new key under `providerConfigs`.
3. Set:
   - `name`
   - `loginUrl`
   - `cancelSelectors` (ordered from most to least reliable)
4. Use that provider id/name in API requests.

Example:

```ts
exampleProvider: {
  name: "Example Provider",
  loginUrl: "https://example.com/login",
  cancelSelectors: [
    "button[data-testid='cancel-subscription']",
    "a[href*='cancel']",
    "button:has-text('Cancel Subscription')"
  ]
}
```

### Guardrail tuning per provider

For each provider request, tune:

- `guardrails.allowedIntents` for safe provider-specific cancel language
- `guardrails.forbiddenIntents` for payment/upgrade/reactivation traps

Recommended baseline allowed intents:

- `cancel`
- `cancel subscription`
- `unsubscribe`
- `end membership`

Recommended baseline forbidden intents:

- `update payment method`
- `change card`
- `change plan`
- `upgrade`
- `reactivate`

## Test and quality commands

```bash
npm test
npm run typecheck
npm run build
```

## Project structure

```text
src/
  index.ts                 # Express server and API handlers
  browser/agent.ts         # Playwright cancellation engine
  guardrails/intents.ts    # Intent matching and URL guardrails
  providers/               # Provider metadata/selectors
  config/index.ts          # Env parsing/validation
  types.ts                 # Request/response/internal types
tests/                     # Jest tests and fixtures
docs/                      # Architecture docs
```
