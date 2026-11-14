// Run Vite on localhost:5188, then:
// ego-browser nodejs -e "await import('file:///D:/workspace/claudecode-test/testplat-auto/web/tests/toast-browser.mjs')"
const task = await taskSpace('testdock-acceptance-fix-20261109');
const page = task.page('p1');
await page.goto('http://127.0.0.1:5188/tests/toast-browser.html');
console.log(await page.snapshot());
await page.click('#success');
await page.click('#error');
const result = await page.evaluate(() => ({
  modalOpen: Boolean(document.querySelector('dialog:modal')),
  toasts: [...document.querySelectorAll('.toast')].map(el => ({
    text: el.textContent,
    topLayer: el.matches(':popover-open'),
    backdrop: getComputedStyle(el, '::backdrop').backdropFilter,
    visible: el.getBoundingClientRect().height > 0,
  })),
}));
if (!result.modalOpen || result.toasts.length !== 2 || result.toasts.some(t => !t.topLayer || !t.visible || t.backdrop !== 'none')) {
  throw new Error(JSON.stringify(result));
}
console.log(result);
await page.waitForFunction(() => !document.querySelector('.toast'));
if (!await page.evaluate(() => Boolean(document.querySelector('dialog:modal')))) throw new Error('Toast closed modal');
console.log('PASS: success/error top-layer display, timer cleanup, modal preserved');
await task.finish({ keep: [] });
