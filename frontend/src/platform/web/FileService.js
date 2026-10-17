/** Web implementation — the <a download> + blob URL pattern already used
 * by the ~12 export call sites (Payroll, backups, audit logs, BAS
 * worksheet, etc. — see docs/platform/MOBILE_DESKTOP_BACKLOG.md for which
 * are migrated to this vs. still inline). */
export async function downloadFile(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
