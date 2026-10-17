'use strict';
// WebdriverIO 10 awaits AsyncFunction through W3C execute/async on Appium.
// Construct the function on the runner, so no page-side eval/CSP exception is needed.
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

module.exports = async function evaluatePage(driver, expression) {
  const outcome = await driver.execute(new AsyncFunction(`
    try { return { ok: true, value: await (${expression}) }; }
    catch (error) { return { ok: false, message: (error && error.message) || String(error) }; }
  `));
  if (!outcome || !outcome.ok) {
    throw new Error(`Page eval failed: ${outcome?.message || 'missing result'}\n${expression}`);
  }
  return outcome.value;
};
