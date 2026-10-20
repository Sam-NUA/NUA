/* Bundled host UI. Does not access credentials or change POS permissions. */
(async () => {
  const native = window.nuaDesktop;
  if (!native) return;
  const info = await native.getInfo();
  document.documentElement.dataset.nuaInput = info.inputMode;
  const bar = document.createElement('aside');
  bar.id = 'nua-desktop-bar';
  bar.setAttribute('aria-label', 'Windows controls');
  const status = document.createElement('span');
  status.textContent = `NUA POS ${info.version} · ${info.inputMode} · Hardware certification pending`;
  const fullscreen = document.createElement('button');
  fullscreen.type = 'button';
  fullscreen.setAttribute('aria-label', 'Toggle full screen (F11; Escape to exit)');
  const applyWindowState = (state) => {
    const expanded = !!state?.fullscreen;
    fullscreen.textContent = expanded ? 'Restore window (Esc)' : 'Full screen (F11)';
    fullscreen.setAttribute('aria-pressed', String(expanded));
  };
  applyWindowState(await native.getWindowState());
  native.onWindowStateChanged(applyWindowState);
  // Windows can change full-screen state through OS shortcuts without a
  // corresponding Electron event. Reconcile the host toolbar with the
  // authoritative BrowserWindow state so the restore control never stays stale.
  let checkingState = false;
  const reconcileWindowState = async () => {
    if (checkingState) return;
    checkingState = true;
    try { applyWindowState(await native.getWindowState()); }
    catch { /* keep last known state until the host recovers */ }
    finally { checkingState = false; }
  };
  window.setInterval(reconcileWindowState, 500);
  window.addEventListener('focus', reconcileWindowState);
  fullscreen.onclick = async () => {
    fullscreen.disabled = true;
    try {
      const state = await native.getWindowState();
      applyWindowState(await native.setFullscreen(!state.fullscreen));
    } catch {
      status.textContent = 'Window mode could not be changed. Try F11 or Escape.';
    } finally {
      fullscreen.disabled = false;
    }
  };
  const print = document.createElement('button');
  print.type = 'button';
  print.textContent = 'Printer test';
  print.onclick = async () => {
    print.disabled = true;
    try {
      const result = await native.printReceipt({ businessName: 'NUA printer test', receiptId: 'TEST — NOT A SALE', items: [{ name: 'Windows spooler test', quantity: 1, totalCents: 0 }], totalCents: 0, footer: 'Verify paper, characters and cutter on the physical device.' });
      status.textContent = result.status === 'submitted' ? 'Submitted to Windows spooler; check the physical printer.' : 'Print cancelled or failed. No automatic retry.';
    } catch { status.textContent = 'Printer unavailable. Check Windows printer settings.'; }
    finally { print.disabled = false; }
  };
  bar.append(status, fullscreen, print);
  document.body.append(bar);
  const reserveBar = () => document.documentElement.style.setProperty('--nua-host-bar-height', `${Math.ceil(bar.getBoundingClientRect().height)}px`);
  reserveBar();
  new ResizeObserver(reserveBar).observe(bar);
})();
