/** Web implementation — the window.open + document.write + print popup
 * pattern already used by services/printer.js's printBrowser and
 * services/docket.js's printDocket, centralized here so both (and any
 * future caller) share one implementation instead of duplicating it. */
export async function printHtml(html) {
  const w = window.open('', '_blank');
  if (!w) return false;
  w.document.write(html);
  w.document.close();
  w.focus();
  await new Promise((resolve) => {
    setTimeout(() => { w.print(); w.close(); resolve(); }, 250);
  });
  return true;
}
