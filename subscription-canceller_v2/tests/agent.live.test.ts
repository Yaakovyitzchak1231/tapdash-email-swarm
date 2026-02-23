import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { cancelSubscription } from '../src/browser/agent';

const LIVE_TESTS_ENABLED = process.env.LIVE_TESTS === 'true';
const LIVE_ARTIFACT_DIR = process.env.LIVE_ARTIFACT_DIR || 'artifacts/live-tests';
const LIVE_TEST_BASE_URL = process.env.LIVE_TEST_BASE_URL || 'https://example.com/account';
const LIVE_TEST_EXPECTED_STATUS = process.env.LIVE_TEST_EXPECTED_STATUS;

async function writeArtifact(fileName: string, data: unknown): Promise<void> {
  const artifactDir = path.resolve(process.cwd(), LIVE_ARTIFACT_DIR);
  await mkdir(artifactDir, { recursive: true });
  const filePath = path.join(artifactDir, fileName);
  await writeFile(filePath, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
}

function normalizeAccountUrl(url: string): string {
  return /\/(account|subscription|manage|settings)/i.test(url)
    ? url
    : `${url.replace(/\/+$/, '')}/account`;
}

describe('live cancellation smoke tests', () => {
  jest.retryTimes(2, { logErrorsBeforeRetry: true });

  const runLive = LIVE_TESTS_ENABLED ? it : it.skip;

  runLive('executes a real browser cancellation flow and emits artifacts', async () => {
    const requestId = `live-${Date.now()}`;
    const startedAt = new Date().toISOString();
    const accountUrl = normalizeAccountUrl(LIVE_TEST_BASE_URL);

    try {
      const result = await cancelSubscription({
        requestId,
        provider: { id: 'live-smoke', name: 'Live Smoke Provider' },
        targetUrls: {
          account: accountUrl,
        },
        guardrails: {
          allowedIntents: ['cancel', 'unsubscribe', 'end membership', 'stop subscription'],
          forbiddenIntents: ['update payment method', 'change card', 'billing details', 'upgrade plan'],
        },
        options: {
          maxSteps: 10,
          maxDurationSeconds: 45,
          dryRun: false,
        },
      });

      const finishedAt = new Date().toISOString();
      await writeArtifact(`${requestId}.result.json`, {
        requestId,
        startedAt,
        finishedAt,
        accountUrl,
        result,
      });

      expect(['success', 'no-safe-cancel', 'error']).toContain(result.status);
      if (result.status === 'error') {
        throw new Error(`Live smoke flow returned error: ${result.summary}`);
      }
      expect(result.actions.length).toBeGreaterThan(0);
      if (LIVE_TEST_EXPECTED_STATUS) {
        expect(result.status).toBe(LIVE_TEST_EXPECTED_STATUS);
      }
    } catch (error) {
      const finishedAt = new Date().toISOString();
      await writeArtifact(`${requestId}.error.json`, {
        requestId,
        startedAt,
        finishedAt,
        accountUrl,
        error: error instanceof Error ? { message: error.message, stack: error.stack } : String(error),
      });
      throw error;
    }
  });
});
