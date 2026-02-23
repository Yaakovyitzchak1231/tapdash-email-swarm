import { cancelSubscription } from '../src/browser/agent';
import { chromium } from 'playwright';

jest.mock('playwright', () => ({
  chromium: {
    launch: jest.fn(),
  },
}));

function createPlaywrightScenario(scenario: 'success' | 'no-safe-cancel' | 'error') {
  let clickedCancel = false;
  const state = { url: 'about:blank' };

  const makeLocator = (selector: string) => {
    const isCancelSelector =
      selector === 'button:has-text("Cancel")' ||
      selector === 'button:has-text("cancel")' ||
      selector.includes('[id*="cancel"');

    const isConfirmTextSelector = selector === 'text=/cancelled/i';

    const visible =
      scenario === 'success'
        ? isCancelSelector || (isConfirmTextSelector && clickedCancel)
        : false;

    return {
      first: () => ({
        isVisible: jest.fn(async () => visible),
        textContent: jest.fn(async () => (isCancelSelector ? 'Cancel Membership' : null)),
        getAttribute: jest.fn(async (name: string) => {
          if (name === 'id' && isCancelSelector) return 'cancel-membership';
          return null;
        }),
        evaluate: jest.fn(async (fn: (el: any) => unknown) =>
          fn({
            id: isCancelSelector ? 'cancel-membership' : '',
            className: '',
            closest: () => null,
            getAttribute: () => null,
            previousElementSibling: null,
          }),
        ),
        click: jest.fn(async () => {
          if (isCancelSelector) {
            clickedCancel = true;
            state.url = 'https://provider.example/cancel-confirmation';
          }
        }),
      }),
      all: jest.fn(async () =>
        visible
          ? [
              {
                first: () => ({
                  isVisible: jest.fn(async () => true),
                  textContent: jest.fn(async () => 'Cancel Membership'),
                  getAttribute: jest.fn(async (name: string) =>
                    name === 'id' ? 'cancel-membership' : null,
                  ),
                  evaluate: jest.fn(async (fn: (el: any) => unknown) =>
                    fn({ tagName: 'BUTTON', closest: () => null, getAttribute: () => null, previousElementSibling: null }),
                  ),
                  click: jest.fn(async () => {
                    clickedCancel = true;
                    state.url = 'https://provider.example/cancel-confirmation';
                  }),
                }),
                isVisible: jest.fn(async () => true),
                textContent: jest.fn(async () => 'Cancel Membership'),
                getAttribute: jest.fn(async (name: string) =>
                  name === 'id' ? 'cancel-membership' : null,
                ),
                evaluate: jest.fn(async (fn: (el: any) => unknown) =>
                  fn({ tagName: 'BUTTON', closest: () => null, getAttribute: () => null, previousElementSibling: null }),
                ),
                click: jest.fn(async () => {
                  clickedCancel = true;
                  state.url = 'https://provider.example/cancel-confirmation';
                }),
              },
            ]
          : [],
      ),
      isVisible: jest.fn(async () => visible),
      textContent: jest.fn(async () => (isCancelSelector ? 'Cancel Membership' : null)),
      getAttribute: jest.fn(async (name: string) => (name === 'id' ? 'cancel-membership' : null)),
      evaluate: jest.fn(async (fn: (el: any) => unknown) =>
        fn({ tagName: 'BUTTON', closest: () => null, getAttribute: () => null, previousElementSibling: null }),
      ),
      click: jest.fn(async () => {
        clickedCancel = true;
        state.url = 'https://provider.example/cancel-confirmation';
      }),
    };
  };

  const page = {
    goto: jest.fn(async (url: string) => {
      if (scenario === 'error' && url.includes('/account')) {
        throw new Error('provider outage');
      }
      state.url = url;
    }),
    setDefaultTimeout: jest.fn(),
    waitForSelector: jest.fn(async () => {}),
    waitForLoadState: jest.fn(async () => {}),
    $: jest.fn(async () => null),
    locator: jest.fn((selector: string) => makeLocator(selector)),
    url: jest.fn(() => state.url),
    title: jest.fn(async () => 'Account'),
  };

  const context = {
    newPage: jest.fn(async () => page),
    close: jest.fn(async () => {}),
  };

  const browser = {
    newContext: jest.fn(async () => context),
    close: jest.fn(async () => {}),
  };

  return { browser, context, page };
}

describe('cancellation agent with mocked browser runtime', () => {
  it('returns success when a safe cancel path is available', async () => {
    const { browser } = createPlaywrightScenario('success');
    (chromium.launch as jest.Mock).mockResolvedValue(browser);
    const baseUrl = 'http://127.0.0.1';

    const result = await cancelSubscription({
      requestId: 'req-1',
      provider: { id: 'demo', name: 'Demo Provider' },
      targetUrls: {
        login: `${baseUrl}/login`,
        account: `${baseUrl}/account`,
      },
      userSession: {
        cookies: [{ name: 'session', value: 'test', domain: '127.0.0.1' }],
      },
      options: { maxSteps: 10, maxDurationSeconds: 30, dryRun: false },
      guardrails: {
        allowedIntents: ['cancel', 'unsubscribe', 'end membership', 'stop subscription'],
        forbiddenIntents: ['update payment method', 'change card', 'billing details', 'upgrade plan'],
      },
    });

    expect(result.status).toBe('success');
    expect(result.outcome?.finalUrl).toContain('cancel-confirmation');
    expect(result.actions.some((a) => a.type === 'click')).toBe(true);
  });

  it('returns no-safe-cancel when no valid cancel controls are found', async () => {
    const { browser } = createPlaywrightScenario('no-safe-cancel');
    (chromium.launch as jest.Mock).mockResolvedValue(browser);
    const baseUrl = 'http://127.0.0.1';

    const result = await cancelSubscription({
      requestId: 'req-2',
      provider: { id: 'demo', name: 'Demo Provider' },
      targetUrls: {
        login: `${baseUrl}/login`,
        account: `${baseUrl}/account`,
      },
      userSession: {
        cookies: [{ name: 'session', value: 'test', domain: '127.0.0.1' }],
      },
      options: { maxSteps: 5, maxDurationSeconds: 5, dryRun: false },
      guardrails: {
        allowedIntents: ['cancel', 'unsubscribe', 'end membership', 'stop subscription'],
        forbiddenIntents: ['update payment method', 'change card', 'billing details', 'change plan'],
      },
    });

    expect(result.status).toBe('no-safe-cancel');
    expect(result.summary.toLowerCase()).toContain('no safe cancellation');
    expect(result.actions.some((a) => a.type === 'click')).toBe(false);
  });

  it('returns error when provider navigation fails', async () => {
    const { browser } = createPlaywrightScenario('error');
    (chromium.launch as jest.Mock).mockResolvedValue(browser);
    const baseUrl = 'http://127.0.0.1';

    const result = await cancelSubscription({
      requestId: 'req-3',
      provider: { id: 'demo', name: 'Demo Provider' },
      targetUrls: {
        login: `${baseUrl}/login`,
        account: `${baseUrl}/account`,
      },
      userSession: {
        cookies: [{ name: 'session', value: 'test', domain: '127.0.0.1' }],
      },
      options: { maxSteps: 5, maxDurationSeconds: 5, dryRun: false },
      guardrails: {
        allowedIntents: ['cancel', 'unsubscribe', 'end membership', 'stop subscription'],
        forbiddenIntents: ['update payment method', 'change card', 'billing details', 'upgrade plan'],
      },
    });

    expect(result.status).toBe('error');
    expect(result.summary.toLowerCase()).toContain('provider outage');
  });
});
