'use strict';

/* Open and close only the probe-owned tab. Never log navigation URLs or account data. */
const fs = require('fs');
const { chromium } = require('playwright');

const lanes = {
  9126: ['beonmeet-chrome-single', 0],
  9132: ['beonmeet-isolated-chrome-2', 1],
  9133: ['beonmeet-isolated-chrome-3', 2],
  9134: ['beonmeet-isolated-chrome-4', 3],
  9135: ['beonmeet-isolated-chrome-5', 4],
};
const roomPath = /^\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/;
const joinLabel = /^(join now|jetzt teilnehmen|rejoindre|پیوستن)$/i;

async function check(port, link) {
  const [host] = lanes[port];
  let browser;
  let page;
  try {
    browser = await chromium.connectOverCDP('http://' + host + ':9223', { timeout: 7000 });
    const context = browser.contexts()[0];
    if (!context) return { status: 'unavailable', reason: 'browser_context_missing' };
    page = await context.newPage();

    try {
      const response = await page.goto(link, { waitUntil: 'domcontentloaded', timeout: 14000 });
      const url = new URL(page.url());
      if (response?.ok() && url.hostname === 'meet.google.com' && roomPath.test(url.pathname)) {
        const visibleJoin = page.getByRole('button', { name: joinLabel }).first();
        const verified = await visibleJoin.waitFor({ state: 'visible', timeout: 6500 })
          .then(() => true, () => false);
        if (verified) return { status: 'verified', reason: 'meet_signed_in_prejoin' };
      }
    } catch {
      // A room may expire or render slowly while the account is still signed in.
    }

    const account = await page.goto('https://myaccount.google.com/', {
      waitUntil: 'domcontentloaded', timeout: 12000,
    });
    const url = new URL(page.url());
    if (url.hostname === 'accounts.google.com') {
      if (/\/challenge(?:\/|$)/.test(url.pathname)) {
        return { status: 'reauthentication_required', reason: 'google_security_challenge' };
      }
      if (await page.locator('input[type=email],input[type=password]').first().isVisible()) {
        return { status: 'reauthentication_required', reason: 'google_credentials_requested' };
      }
      if (/accountchooser/i.test(url.pathname)) {
        return { status: 'inconclusive', reason: 'google_account_selection' };
      }
    }
    if (account?.ok() && url.hostname === 'myaccount.google.com') {
      return { status: 'inconclusive', reason: 'account_page_reachable_meet_unverified' };
    }
    return { status: 'inconclusive', reason: 'google_account_check_unconfirmed' };
  } catch {
    return browser
      ? { status: 'inconclusive', reason: 'probe_navigation_or_render_failed' }
      : { status: 'unavailable', reason: 'browser_connection_failed' };
  } finally {
    if (page) await page.close().catch(() => {});
    // For connectOverCDP, close disconnects this client and leaves Chrome running.
    if (browser) await browser.close().catch(() => {});
  }
}

async function main() {
  const { ports } = JSON.parse(fs.readFileSync('/qa-input.json', 'utf8'));
  const { links } = JSON.parse(fs.readFileSync('/qa-links.json', 'utf8'));
  if (!Array.isArray(ports) || ports.length > 5 || !Array.isArray(links) || links.length !== 5) {
    throw Error('Invalid private watchdog input');
  }
  for (const port of ports) {
    if (!Object.hasOwn(lanes, port) || !/^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/.test(links[lanes[port][1]])) {
      throw Error('Invalid lane or fixture');
    }
  }
  const workers = {};
  async function scan(port) {
    const result = await check(port, links[lanes[port][1]]);
    workers['http://127.0.0.1:' + port] = { ...result, checked_at: Math.floor(Date.now() / 1000) };
  }
  for (let i = 0; i < ports.length; i += 2) {
    await Promise.all(ports.slice(i, i + 2).map(scan));
  }
  process.stdout.write(JSON.stringify({ workers }) + '\n');
}

main().catch(error => {
  console.error('AUTH_MONITOR_FAILED', error.name);
  process.exitCode = 2;
});
