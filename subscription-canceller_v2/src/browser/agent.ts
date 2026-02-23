/**
 * Playwright-based browser automation agent for subscription cancellation
 */

import { 
  Browser, 
  Page, 
  BrowserContext, 
  chromium,
  Locator,
} from 'playwright';
import {
  CancelSubscriptionRequest,
  CancelSubscriptionResponse,
  CancelSubscriptionStatus,
  ActionLog,
  CancellationOutcome,
  ErrorInfo,
  ElementContext,
  ErrorCodes,
} from '../types';
import { matchIntent, isUrlNavigationAllowed } from '../guardrails/intents';

// ============================================================================
// Types
// ============================================================================

interface BrowserSession {
  browser: Browser;
  context: BrowserContext;
  page: Page;
}

interface CancellationResult {
  status: CancelSubscriptionStatus;
  summary: string;
  outcome?: CancellationOutcome;
  actions: ActionLog[];
  error?: ErrorInfo;
}

// ============================================================================
// Constants
// ============================================================================

const DEFAULT_TIMEOUT = 30000;
const DEFAULT_MAX_STEPS = 40;
const DEFAULT_MAX_DURATION = 300;

// ============================================================================
// Browser Agent Class
// ============================================================================

export class BrowserAgent {
  private session: BrowserSession | null = null;
  private actions: ActionLog[] = [];
  private stepCount = 0;
  private startTime: number = 0;
  private request: CancelSubscriptionRequest;

  constructor(request: CancelSubscriptionRequest) {
    this.request = request;
    this.actions = [];
    this.stepCount = 0;
  }

  /**
   * Main entry point for subscription cancellation
   */
  async cancel(): Promise<CancelSubscriptionResponse> {
    this.startTime = Date.now();
    
    try {
      // Validate request
      this.validateRequest();
      
      // Launch browser
      await this.launchBrowser();
      
      // Perform cancellation
      const result = await this.performCancellation();
      
      // Build response
      return this.buildResponse(result);
      
    } catch (error) {
      const result: CancellationResult = {
        status: 'error',
        summary: `Cancellation failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
        actions: this.actions,
        error: {
          code: ErrorCodes.UNEXPECTED_ERROR,
          message: error instanceof Error ? error.message : 'Unknown error',
          stack: error instanceof Error ? error.stack : undefined,
        },
      };
      
      return this.buildResponse(result);
      
    } finally {
      await this.closeBrowser();
    }
  }

  /**
   * Validates the incoming request
   */
  private validateRequest(): void {
    if (!this.request.requestId) {
      throw new Error('requestId is required');
    }
    
    if (!this.request.provider?.id) {
      throw new Error('provider.id is required');
    }
    
    if (!this.request.guardrails) {
      throw new Error('guardrails configuration is required');
    }
  }

  /**
   * Launches the browser with configured session
   */
  private async launchBrowser(): Promise<void> {
    const options = this.request.options || {};
    const headless = !options.dryRun;
    
    try {
      const browser = await chromium.launch({
        headless,
        timeout: DEFAULT_TIMEOUT,
        chromiumSandbox: false,
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
      });
      
      const context = await browser.newContext({
        userAgent: this.request.userSession?.headers?.['User-Agent'],
        storageState: this.request.userSession?.cookies?.length
          ? {
              cookies: this.request.userSession.cookies.map(c => ({
                name: c.name,
                value: c.value,
                domain: c.domain,
                path: c.path || '/',
                expires: c.expires || Math.floor(Date.now() / 1000) + 3600,
                httpOnly: c.httpOnly || false,
                secure: c.secure || false,
                sameSite: (c.sameSite as 'Strict' | 'Lax' | 'None') || 'Lax',
              })),
              origins: [],
            }
          : undefined,
      });
      
      const page = await context.newPage();
      page.setDefaultTimeout(DEFAULT_TIMEOUT);
      
      this.session = { browser, context, page };
      
      this.logAction({
        step: ++this.stepCount,
        type: 'navigate',
        description: 'Browser launched successfully',
        timestamp: new Date().toISOString(),
      });
      
    } catch (error) {
      throw new Error(`Failed to launch browser: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  /**
   * Main cancellation logic
   */
  private async performCancellation(): Promise<CancellationResult> {
    const { page } = this.session!;
    const maxSteps = this.request.options?.maxSteps || DEFAULT_MAX_STEPS;
    const maxDuration = (this.request.options?.maxDurationSeconds || DEFAULT_MAX_DURATION) * 1000;
    
    // Determine if login is needed and navigate accordingly
    const needsLogin = this.request.targetUrls.login && !this.request.userSession?.cookies?.length;
    
    if (needsLogin) {
      // Navigate to login page first
      await this.navigateTo(this.request.targetUrls.login!);
      const loginSuccess = await this.attemptLogin();
      if (!loginSuccess) {
        return {
          status: 'error',
          summary: 'Login failed',
          actions: this.actions,
          error: { code: ErrorCodes.LOGIN_FAILED, message: 'Unable to complete login process' },
        };
      }
    }
    
    // Navigate to account page if specified
    if (this.request.targetUrls.account) {
      await this.navigateTo(this.request.targetUrls.account);
    }
    
    // Navigate to subscription page if specified
    if (this.request.targetUrls.subscription) {
      await this.navigateTo(this.request.targetUrls.subscription);
    }
    
    if (!this.request.targetUrls.account && !this.request.targetUrls.subscription && !needsLogin) {
      return {
        status: 'error',
        summary: 'No starting URL provided',
        actions: this.actions,
        error: { code: ErrorCodes.INVALID_REQUEST, message: 'No valid starting URL in targetUrls' },
      };
    }
    
    // Search for cancel elements and interact
    let cancellationConfirmed = false;
    let noSafeCancel = false;
    
    while (this.stepCount < maxSteps && Date.now() - this.startTime < maxDuration) {
      // Find potential cancel elements
      const cancelElements = await this.findCancelElements();
      
      if (cancelElements.length === 0) {
        // No cancel elements found - check if we're already on a confirmation page
        const confirmed = await this.checkForCancellationConfirmation();
        if (confirmed) {
          cancellationConfirmed = true;
          break;
        }
        
        // Try to find navigation elements to get to subscription settings
        const navResult = await this.findSubscriptionNavigation();
        if (!navResult) {
          noSafeCancel = true;
          break;
        }
        continue;
      }
      
      // Validate and click the most promising cancel element
      const validElement = await this.findValidCancelElement(cancelElements);
      
      if (!validElement) {
        noSafeCancel = true;
        break;
      }
      
      // Click the element
      await this.clickElement(validElement.locator, validElement.context);
      
      // Check for confirmation
      const confirmed = await this.checkForCancellationConfirmation();
      if (confirmed) {
        cancellationConfirmed = true;
        break;
      }
      
      // Check for confirmation dialogs/modals
      const confirmButton = await this.findConfirmationButton();
      if (confirmButton) {
        await this.clickElement(confirmButton.locator, confirmButton.context);
        
        const finalCheck = await this.checkForCancellationConfirmation();
        if (finalCheck) {
          cancellationConfirmed = true;
          break;
        }
      }
    }
    
    // Build result
    if (cancellationConfirmed) {
      const finalUrl = page.url();
      const confirmationText = await this.extractConfirmationText();
      
      return {
        status: 'success',
        summary: `Successfully cancelled ${this.request.provider.name} subscription`,
        outcome: {
          finalUrl,
          cancelConfirmationText: confirmationText,
          cancelledAt: new Date().toISOString(),
        },
        actions: this.actions,
      };
    }
    
    if (noSafeCancel) {
      return {
        status: 'no-safe-cancel',
        summary: 'No safe cancellation path found within guardrails',
        actions: this.actions,
      };
    }
    
    return {
      status: 'error',
      summary: 'Cancellation did not complete within time/step limits',
      actions: this.actions,
      error: { code: ErrorCodes.TIMEOUT, message: 'Exceeded maximum steps or duration' },
    };
  }

  /**
   * Navigate to a URL
   */
  private async navigateTo(url: string): Promise<void> {
    const { page } = this.session!;
    
    // Validate URL is allowed
    const urlCheck = isUrlNavigationAllowed(url, this.request.guardrails);
    if (!urlCheck.allowed) {
      throw new Error(`Navigation blocked: ${urlCheck.reason}`);
    }
    
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: DEFAULT_TIMEOUT });
    
    this.logAction({
      step: ++this.stepCount,
      type: 'navigate',
      url,
      description: `Navigated to ${url}`,
      timestamp: new Date().toISOString(),
    });
  }

  /**
   * Attempt to log in using provided credentials
   */
  private async attemptLogin(): Promise<boolean> {
    const { page } = this.session!;
    const credentials = this.request.credentials;
    
    if (!credentials) {
      return false;
    }
    
    try {
      // Wait for login form
      await page.waitForSelector('input[type="email"], input[type="text"][name*="email"], input[name*="user"]', { timeout: 5000 });
      
      // Fill email/username
      const emailInput = await page.$('input[type="email"]') || 
                         await page.$('input[name*="email"]') ||
                         await page.$('input[name*="user"]');
      
      if (emailInput && (credentials.email || credentials.username)) {
        await emailInput.fill(credentials.email || credentials.username || '');
      }
      
      // Fill password
      const passwordInput = await page.$('input[type="password"]');
      if (passwordInput && credentials.password) {
        await passwordInput.fill(credentials.password);
      }
      
      // Find and click login button
      const loginButton = await this.findLoginButton();
      if (loginButton) {
        await loginButton.click();
        await page.waitForLoadState('domcontentloaded');
      }
      
      this.logAction({
        step: ++this.stepCount,
        type: 'formSubmit',
        description: 'Submitted login form',
        metadata: { fieldsUsed: ['email', 'password'] },
        timestamp: new Date().toISOString(),
      });
      
      return true;
      
    } catch (error) {
      this.logAction({
        step: ++this.stepCount,
        type: 'formSubmit',
        description: `Login attempt failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
        timestamp: new Date().toISOString(),
      });
      return false;
    }
  }

  /**
   * Find login button
   */
  private async findLoginButton(): Promise<Locator | null> {
    const { page } = this.session!;
    
    const selectors = [
      'button[type="submit"]',
      'input[type="submit"]',
      'button:has-text("Log in")',
      'button:has-text("Sign in")',
      'button:has-text("Login")',
      'a:has-text("Log in")',
      'a:has-text("Sign in")',
    ];
    
    for (const selector of selectors) {
      const locator = page.locator(selector).first();
      if (await locator.isVisible({ timeout: 1000 }).catch(() => false)) {
        return locator;
      }
    }
    
    return null;
  }

  /**
   * Find elements that might be cancel/unsubscribe buttons
   */
  private async findCancelElements(): Promise<Array<{ locator: Locator; context: ElementContext }>> {
    const { page } = this.session!;
    const elements: Array<{ locator: Locator; context: ElementContext }> = [];
    
    const cancelPatterns = [
      'button:has-text("Cancel")',
      'button:has-text("cancel")',
      'a:has-text("Cancel")',
      'a:has-text("cancel")',
      'button:has-text("Unsubscribe")',
      'button:has-text("unsubscribe")',
      'a:has-text("Unsubscribe")',
      'a:has-text("unsubscribe")',
      'button:has-text("End")',
      'button:has-text("Stop")',
      'button:has-text("Terminate")',
      'input[value*="Cancel" i]',
      'input[value*="Unsubscribe" i]',
      '[class*="cancel" i]',
      '[id*="cancel" i]',
      '[data-action*="cancel" i]',
    ];
    
    for (const pattern of cancelPatterns) {
      try {
        const locators = await page.locator(pattern).all();
        for (const locator of locators) {
          if (await locator.isVisible({ timeout: 500 }).catch(() => false)) {
            const context = await this.extractElementContext(locator);
            if (context) {
              elements.push({ locator, context });
            }
          }
        }
      } catch {
        // Continue to next pattern
      }
    }
    
    return elements;
  }

  /**
   * Extract context from an element for intent matching
   */
  private async extractElementContext(locator: Locator): Promise<ElementContext | null> {
    try {
      const element = locator.first();
      const text = await element.textContent() || '';
      const ariaLabel = await element.getAttribute('aria-label') || undefined;
      const title = await element.getAttribute('title') || undefined;
      const name = await element.getAttribute('name') || undefined;
      const value = await element.getAttribute('value') || undefined;
      const type = await element.getAttribute('type') || undefined;
      const role = await element.getAttribute('role') || undefined;
      const tagName = await element.evaluate(el => el.tagName.toLowerCase());
      
      const url = this.session?.page.url() || '';
      const pageTitle = await this.session?.page.title() || '';
      
      // Get nearby labels
      const nearbyLabels = await element.evaluate((el) => {
        const labels: string[] = [];
        
        // Check for associated label
        const parent = el.closest('label');
        if (parent && parent !== el) {
          labels.push(parent.textContent?.trim() || '');
        }
        
        // Check for aria-labelledby
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
          const labelEl = document.getElementById(labelledBy);
          if (labelEl) labels.push(labelEl.textContent?.trim() || '');
        }
        
        // Check for preceding text
        const prev = el.previousElementSibling;
        if (prev && prev.textContent) {
          labels.push(prev.textContent.trim());
        }
        
        return labels.filter(l => l.length > 0);
      });
      
      return {
        tagName,
        text,
        ariaLabel,
        title,
        name,
        value,
        type,
        role,
        nearbyLabels,
        url,
        pageTitle,
      };
    } catch {
      return null;
    }
  }

  /**
   * Find a valid cancel element that passes guardrails
   */
  private async findValidCancelElement(
    elements: Array<{ locator: Locator; context: ElementContext }>
  ): Promise<{ locator: Locator; context: ElementContext } | null> {
    for (const { locator, context } of elements) {
      const intentResult = matchIntent(context, this.request.guardrails);
      
      if (intentResult.isAllowed && !intentResult.isForbidden) {
        return { locator, context };
      }
    }
    
    return null;
  }

  /**
   * Click an element
   */
  private async clickElement(locator: Locator, context: ElementContext): Promise<void> {
    const { page } = this.session!;
    
    await locator.click();
    await page.waitForLoadState('domcontentloaded').catch(() => {});
    
    this.logAction({
      step: ++this.stepCount,
      type: 'click',
      selector: await locator.evaluate(el => el.id ? `#${el.id}` : el.className ? `.${el.className.split(' ')[0]}` : undefined).catch(() => undefined),
      text: context.text,
      description: `Clicked "${context.text || 'element'}"`,
      timestamp: new Date().toISOString(),
    });
  }

  /**
   * Find confirmation button after initial cancel click
   */
  private async findConfirmationButton(): Promise<{ locator: Locator; context: ElementContext } | null> {
    const { page } = this.session!;
    
    const confirmPatterns = [
      'button:has-text("Confirm")',
      'button:has-text("Yes")',
      'button:has-text("Continue")',
      'button:has-text("Proceed")',
      'button:has-text("OK")',
      'input[value*="Confirm" i]',
      'input[value*="Yes" i]',
    ];
    
    for (const pattern of confirmPatterns) {
      try {
        const locator = page.locator(pattern).first();
        if (await locator.isVisible({ timeout: 2000 }).catch(() => false)) {
          const context = await this.extractElementContext(locator);
          if (context) {
            const intentResult = matchIntent(context, this.request.guardrails);
            if (intentResult.isAllowed) {
              return { locator, context };
            }
          }
        }
      } catch {
        // Continue to next pattern
      }
    }
    
    return null;
  }

  /**
   * Check if current page shows cancellation confirmation
   */
  private async checkForCancellationConfirmation(): Promise<boolean> {
    const { page } = this.session!;
    
    const confirmationPatterns = [
      'text=/cancelled/i',
      'text=/unsubscribed/i',
      'text=/membership.*ended/i',
      'text=/subscription.*ended/i',
      'text=/no longer.*active/i',
      'text=/successfully.*cancelled/i',
      'text=/will be cancelled/i',
      '[class*="confirmation"]',
      '[class*="success"]',
    ];
    
    for (const pattern of confirmationPatterns) {
      try {
        const visible = await page.locator(pattern).first().isVisible({ timeout: 1000 }).catch(() => false);
        if (visible) {
          return true;
        }
      } catch {
        // Continue
      }
    }
    
    // Check URL for confirmation indicators
    const url = page.url().toLowerCase();
    if (url.includes('cancel') && (url.includes('confirm') || url.includes('success') || url.includes('complete'))) {
      return true;
    }
    
    return false;
  }

  /**
   * Extract confirmation text from page
   */
  private async extractConfirmationText(): Promise<string | undefined> {
    const { page } = this.session!;
    
    try {
      // Look for common confirmation message patterns
      const confirmationSelectors = [
        '[class*="confirmation"]',
        '[class*="success"]',
        '[class*="message"]',
        '[role="alert"]',
        '.toast',
        '.notification',
      ];
      
      for (const selector of confirmationSelectors) {
        const element = page.locator(selector).first();
        const text = await element.textContent({ timeout: 1000 }).catch(() => null);
        if (text && text.toLowerCase().includes('cancel')) {
          return text.trim();
        }
      }
    } catch {
      // Return undefined if extraction fails
    }
    
    return undefined;
  }

  /**
   * Try to find navigation to subscription settings
   */
  private async findSubscriptionNavigation(): Promise<boolean> {
    const { page } = this.session!;
    
    const navPatterns = [
      'a:has-text("Account")',
      'a:has-text("Settings")',
      'a:has-text("Subscription")',
      'a:has-text("Membership")',
      'a:has-text("Billing")',
      '[class*="account"]',
      '[class*="settings"]',
      '[class*="subscription"]',
    ];
    
    for (const pattern of navPatterns) {
      try {
        const locator = page.locator(pattern).first();
        if (await locator.isVisible({ timeout: 1000 }).catch(() => false)) {
          const context = await this.extractElementContext(locator);
          if (context) {
            await this.clickElement(locator, context);
            return true;
          }
        }
      } catch {
        // Continue
      }
    }
    
    return false;
  }

  /**
   * Log an action
   */
  private logAction(action: ActionLog): void {
    this.actions.push(action);
  }

  /**
   * Build the response object
   */
  private buildResponse(result: CancellationResult): CancelSubscriptionResponse {
    return {
      requestId: this.request.requestId,
      status: result.status,
      summary: result.summary,
      provider: this.request.provider,
      outcome: result.outcome,
      actions: result.actions,
      logsRef: {
        id: this.request.requestId,
        location: `internal-logging-system://ai-browser/cancel-subscription/${this.request.requestId}`,
      },
      error: result.error,
    };
  }

  /**
   * Close browser session
   */
  private async closeBrowser(): Promise<void> {
    if (this.session) {
      try {
        await this.session.context.close().catch(() => {});
        await this.session.browser.close().catch(() => {});
      } catch {
        // Ignore cleanup errors
      }
      this.session = null;
    }
  }
}

// ============================================================================
// Export Functions
// ============================================================================

/**
 * Main function to cancel a subscription
 */
export async function cancelSubscription(
  request: CancelSubscriptionRequest
): Promise<CancelSubscriptionResponse> {
  const agent = new BrowserAgent(request);
  return await agent.cancel();
}

export default BrowserAgent;
