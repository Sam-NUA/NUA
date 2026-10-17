/** Electron implementation — the web `<a download>` pattern is silently
 * blocked inside the Windows host: main.cjs's session does
 * `on('will-download', event => event.preventDefault())` for every
 * download, with no error surfaced to the caller. Routes through
 * `nua:save-file` instead, which shows a real native Save dialog and
 * writes the bytes directly — the ~12 existing export call sites (CSV/
 * PDF reports, payroll, backups, audit logs) get a real file on disk
 * instead of a silently-dropped download. */
export async function downloadFile(blob, filename) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  return window.nuaDesktop.saveFile(filename, bytes);
}
