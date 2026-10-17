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
  status.textContent = `Windows foundation ${info.version} · ${info.inputMode} · Hardware certification pending`;
  const fullscreen = document.createElement('button');
  fullscreen.type = 'button';
  fullscreen.textContent = 'Full screen';
  let expanded = false;
  fullscreen.onclick = async () => {
    expanded = await native.setFullscreen(!expanded);
    fullscreen.textContent = expanded ? 'Exit full screen' : 'Full screen';
    fullscreen.setAttribute('aria-pressed', String(expanded));
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
