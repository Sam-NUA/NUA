'use strict';
function escape(value) {
  return value.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function text(value, max) {
  if (typeof value !== 'string' || value.length > max || /[\x00-\x08\x0b-\x1f]/.test(value)) throw new Error('Invalid receipt text');
  return escape(value);
}
function money(value) {
  if (!Number.isSafeInteger(value) || value < 0 || value > 100000000) throw new Error('Invalid receipt amount');
  return (value / 100).toFixed(2);
}
function renderReceipt(receipt) {
  if (!receipt || !Array.isArray(receipt.items) || !receipt.items.length || receipt.items.length > 200) throw new Error('Invalid receipt');
  const rows = receipt.items.map(item => {
    if (!Number.isSafeInteger(item.quantity) || item.quantity < 1 || item.quantity > 9999) throw new Error('Invalid quantity');
    return `<tr><td>${text(item.name, 160)} × ${item.quantity}</td><td>$${money(item.totalCents)}</td></tr>`;
  }).join('');
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><style>@page{margin:4mm}body{font:12px monospace;max-width:72mm}table{width:100%}td:last-child{text-align:right}h1{font-size:18px}</style></head><body><h1>${text(receipt.businessName,120)}</h1><p>${text(receipt.receiptId,100)}</p><table>${rows}</table><p>Total $${money(receipt.totalCents)}</p><p>${text(receipt.footer || '',300)}</p></body></html>`;
}
module.exports = { renderReceipt };
