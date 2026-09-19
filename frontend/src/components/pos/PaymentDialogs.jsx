import React from 'react';
import { Check, ChevronLeft, Copy, Smartphone } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Card, CardContent } from '../ui/card';
import { Badge } from '../ui/badge';

/** QR Code payment dialog (e.g. Aussie payID, store-branded). */
export function QrPaymentDialog({ open, onClose, qrData, total, onConfirm, loading }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm" data-testid="qr-payment-dialog">
        <DialogHeader><DialogTitle>Scan QR to Pay</DialogTitle></DialogHeader>
        <div className="flex flex-col items-center py-4 space-y-4">
          <div className="bg-white p-4 rounded-xl shadow-inner border">
            {qrData?.qrData && <QRCodeSVG value={qrData.qrData} size={200} level="M" includeMargin />}
          </div>
          <div className="text-center">
            <p className="text-3xl font-bold">${total.toFixed(2)}</p>
            <p className="text-sm text-gray-500 mt-1">Transaction: {qrData?.transactionId}</p>
          </div>
          <Badge variant="outline" className="text-amber-600 border-amber-300 bg-amber-50">Waiting for payment...</Badge>
          <Button className="w-full bg-green-600 hover:bg-green-700 text-white" onClick={onConfirm} disabled={loading} data-testid="qr-confirm-btn">
            <Check size={18} className="mr-2" /> Confirm Payment Received
          </Button>
          <Button variant="ghost" className="w-full" onClick={onClose}><ChevronLeft size={16} className="mr-1" /> Back</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** UPI payment dialog (India). */
export function UpiPaymentDialog({ open, onClose, qrData, total, onConfirm, loading, onCopyUpi }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm" data-testid="upi-payment-dialog">
        <DialogHeader><DialogTitle>UPI Payment</DialogTitle></DialogHeader>
        <div className="flex flex-col items-center py-4 space-y-4">
          <div className="bg-white p-4 rounded-xl shadow-inner border">
            {qrData?.qrData && <QRCodeSVG value={qrData.qrData} size={180} level="M" includeMargin />}
          </div>
          <div className="text-center">
            <p className="text-3xl font-bold">${total.toFixed(2)}</p>
            {qrData?.merchantUpi && (
              <div className="flex items-center gap-2 justify-center mt-2 text-sm text-gray-600 bg-gray-50 px-3 py-1.5 rounded-full">
                <span className="font-mono">{qrData.merchantUpi}</span>
                <button onClick={() => onCopyUpi(qrData.merchantUpi)} className="text-gray-400 hover:text-gray-700"><Copy size={14} /></button>
              </div>
            )}
            <p className="text-xs text-gray-400 mt-2">Scan QR or pay to UPI ID above</p>
          </div>
          <Badge variant="outline" className="text-amber-600 border-amber-300 bg-amber-50">Awaiting UPI confirmation...</Badge>
          <Button className="w-full bg-green-600 hover:bg-green-700 text-white" onClick={onConfirm} disabled={loading} data-testid="upi-confirm-btn">
            <Check size={18} className="mr-2" /> Confirm Payment Received
          </Button>
          <Button variant="ghost" className="w-full" onClick={onClose}><ChevronLeft size={16} className="mr-1" /> Back</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Split payment dialog — supports equal/custom split & per-part method. */
export function SplitPaymentDialog({
  open, onClose, total, splitParts, splitMode, splitCount,
  onSetMode, onChangeCount, onUpdatePart, onPayPart, splitRemaining, loading, activeSplitIndex,
  seatsAvailable = false,
  cartItems = [], itemAssignments = {}, onAdjustItemAssignment,
  customers = [],
}) {
  const paidSoFar = Math.max(0, Math.round((Number(total) - Number(splitRemaining)) * 100) / 100);
  const allPaid = splitRemaining === 0 && splitParts.length > 0;
  // Once anyone's paid, assignments are locked — reshuffling items after a
  // guest has already been charged would silently change what everyone owes.
  const assignmentsLocked = splitParts.some(p => p.status === 'confirmed');
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto" data-testid="split-payment-dialog">
        <DialogHeader>
          <DialogTitle>Split Payment</DialogTitle>
        </DialogHeader>
        {/* Prominent bill breakdown — remaining is the number the cashier
            actually cares about after each guest pays. */}
        <div className="grid grid-cols-3 gap-2 my-2 text-center">
          <div className="rounded-lg bg-gray-50 border p-2" data-testid="split-total-tile">
            <p className="text-[10px] uppercase text-gray-500 font-bold">Bill total</p>
            <p className="text-xl font-bold">${Number(total).toFixed(2)}</p>
          </div>
          <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-2" data-testid="split-paid-tile">
            <p className="text-[10px] uppercase text-emerald-700 font-bold">Paid so far</p>
            <p className="text-xl font-bold text-emerald-700">${paidSoFar.toFixed(2)}</p>
          </div>
          <div className={`rounded-lg border p-2 ${allPaid ? 'bg-emerald-100 border-emerald-300' : 'bg-orange-50 border-orange-200'}`} data-testid="split-remaining-tile">
            <p className={`text-[10px] uppercase font-bold ${allPaid ? 'text-emerald-700' : 'text-orange-700'}`}>{allPaid ? 'All settled' : 'Remaining'}</p>
            <p className={`text-xl font-bold ${allPaid ? 'text-emerald-700' : 'text-orange-700'}`}>${Number(splitRemaining).toFixed(2)}</p>
          </div>
        </div>
        {(() => {
          if (splitMode === 'custom' && splitParts.length > 0) {
            const sum = splitParts.reduce((s, p) => s + Number(p.amount || 0), 0);
            const off = Math.round((sum - total) * 100) / 100;
            if (Math.abs(off) > 0.005) {
              return (
                <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700" data-testid="split-imbalance-warning">
                  Splits {off > 0 ? 'exceed' : 'are below'} the bill by ${Math.abs(off).toFixed(2)} — fix before closing.
                </div>
              );
            }
          }
          return null;
        })()}
        <div className="space-y-4 py-2">
          <div className="flex items-center gap-3">
            <div className={`flex items-center gap-2 ${splitMode === 'seat' ? 'opacity-40 pointer-events-none' : ''}`}>
              <span className="text-sm font-medium text-gray-600">Split into</span>
              <div className="flex items-center border rounded-lg overflow-hidden">
                <button className="px-3 py-1.5 hover:bg-gray-100 text-sm" onClick={() => splitCount > 2 && onChangeCount(splitCount - 1)}>-</button>
                <span className="px-3 py-1.5 font-bold text-sm border-x" data-testid="split-count">{splitCount}</span>
                <button className="px-3 py-1.5 hover:bg-gray-100 text-sm" onClick={() => splitCount < 10 && onChangeCount(splitCount + 1)}>+</button>
              </div>
            </div>
            <div className="flex gap-1 ml-auto">
              {['equal', 'custom', 'items', ...(seatsAvailable ? ['seat'] : [])].map(m => (
                <button key={m} onClick={() => onSetMode(m)}
                  className={`px-3 py-1.5 text-xs rounded-full font-medium transition-colors ${splitMode === m ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
                  data-testid={`split-mode-${m}`}>
                  {m === 'equal' ? 'Equal' : m === 'custom' ? 'Custom' : m === 'items' ? 'By item' : 'By seat'}
                </button>
              ))}
            </div>
          </div>
          {splitMode === 'items' && (
            <div className="space-y-2 border rounded-lg p-2.5 bg-gray-50" data-testid="split-item-assignment">
              {assignmentsLocked && (
                <p className="text-[10px] text-amber-600">Assignments are locked — someone's already paid.</p>
              )}
              {cartItems.length === 0 ? (
                <p className="text-xs text-gray-400 text-center py-2">Cart is empty</p>
              ) : cartItems.map(item => {
                const perGuest = itemAssignments[item.id] || {};
                const assigned = Object.values(perGuest).reduce((s, q) => s + (q || 0), 0);
                const unassigned = Math.max(0, (item.quantity || 0) - assigned);
                return (
                  <div key={item.id} className="bg-white border rounded-md p-2" data-testid={`split-item-row-${item.id}`}>
                    <div className="flex items-center justify-between text-xs mb-1.5">
                      <span className="font-medium truncate">{item.quantity}× {item.name}</span>
                      {unassigned > 0 && (
                        <span className="text-amber-600 font-medium whitespace-nowrap ml-2" data-testid={`split-item-unassigned-${item.id}`}>
                          {unassigned} unassigned
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {Array.from({ length: splitCount }, (_, g) => g).map(g => (
                        <div key={g} className="flex items-center border rounded-md overflow-hidden" data-testid={`split-item-guest-${item.id}-${g}`}>
                          <button
                            className="px-1.5 py-0.5 text-xs hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
                            disabled={assignmentsLocked || (perGuest[g] || 0) <= 0}
                            onClick={() => onAdjustItemAssignment(item.id, g, -1)}
                            data-testid={`split-item-minus-${item.id}-${g}`}>-</button>
                          <span className="px-1.5 text-[11px] font-semibold border-x min-w-[2.75rem] text-center" data-testid={`split-item-qty-${item.id}-${g}`}>
                            G{g + 1}: {perGuest[g] || 0}
                          </span>
                          <button
                            className="px-1.5 py-0.5 text-xs hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed"
                            disabled={assignmentsLocked || unassigned <= 0}
                            onClick={() => onAdjustItemAssignment(item.id, g, 1)}
                            data-testid={`split-item-plus-${item.id}-${g}`}>+</button>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          <div className="space-y-3">
            {splitParts.map((part, idx) => (
              <Card key={idx} className={`border ${part.status === 'confirmed' ? 'border-green-300 bg-green-50/50' : ''}`}
                data-testid={`split-part-${idx}`}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-3">
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${part.status === 'confirmed' ? 'bg-green-600 text-white' : 'bg-gray-200 text-gray-700'}`}>
                      {part.status === 'confirmed' ? <Check size={16} /> : idx + 1}
                    </div>
                    <div className="flex-1 space-y-2">
                      {(part.seatItems || part.assignedItems)?.length > 0 && (
                        <p className="text-[10px] text-gray-500 leading-tight" data-testid={`split-seat-items-${idx}`}>
                          {(part.seatItems || part.assignedItems).map(i => `${i.quantity}× ${i.name}`).join(' · ')}
                        </p>
                      )}
                      <div className="flex gap-2">
                        <Input placeholder="Guest name" value={part.payerName} className="h-8 text-sm"
                          onChange={e => onUpdatePart(idx, 'payerName', e.target.value)}
                          disabled={part.status === 'confirmed'} data-testid={`split-name-${idx}`} />
                        {splitMode === 'custom' ? (
                          <Input type="number" step="0.01" min="0" value={part.amount} className="h-8 text-sm w-28"
                            onChange={e => onUpdatePart(idx, 'amount', parseFloat(e.target.value) || 0)}
                            disabled={part.status === 'confirmed'} data-testid={`split-amount-${idx}`} />
                        ) : (
                          <span className="font-bold text-sm whitespace-nowrap self-center">${part.amount.toFixed(2)}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5">
                        {['Card', 'Cash', 'UPI', 'QR Code'].map(method => (
                          <button key={method} onClick={() => part.status !== 'confirmed' && onUpdatePart(idx, 'method', method)}
                            className={`px-2 py-1 text-[11px] rounded-md font-medium transition-colors ${part.method === method ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}
                            disabled={part.status === 'confirmed'} data-testid={`split-method-${idx}-${method.toLowerCase().replace(' ', '-')}`}>
                            {method}
                          </button>
                        ))}
                      </div>
                      {customers.length > 0 && (
                        <div className="flex items-center gap-1.5">
                          <select
                            className="h-7 text-[11px] border rounded px-1.5 bg-white flex-1 min-w-0"
                            value={part.customerId || ''}
                            disabled={part.status === 'confirmed'}
                            onChange={e => {
                              const c = customers.find(x => x.id === e.target.value);
                              onUpdatePart(idx, 'customerId', c ? c.id : null);
                              onUpdatePart(idx, 'pointsRedeemed', 0);
                            }}
                            data-testid={`split-customer-${idx}`}
                          >
                            <option value="">No loyalty account</option>
                            {customers.map(c => (
                              <option key={c.id} value={c.id}>{c.name} {c.points ? `(${c.points} pts)` : ''}</option>
                            ))}
                          </select>
                          {part.customerId && (
                            <Input type="number" min="0" step="1" placeholder="Redeem pts" value={part.pointsRedeemed || ''}
                              className="h-7 text-[11px] w-24"
                              onChange={e => onUpdatePart(idx, 'pointsRedeemed', parseInt(e.target.value) || 0)}
                              disabled={part.status === 'confirmed'} data-testid={`split-points-${idx}`} />
                          )}
                        </div>
                      )}
                    </div>
                    {part.status !== 'confirmed' ? (
                      <Button size="sm" className="bg-green-600 hover:bg-green-700 text-white h-8 px-3 disabled:opacity-50 disabled:cursor-not-allowed"
                        onClick={() => onPayPart(idx)}
                        disabled={(loading && activeSplitIndex === idx) || Number(part.amount || 0) <= 0 || Number(part.amount || 0) > splitRemaining + 0.005}
                        data-testid={`split-pay-${idx}`}>
                        {loading && activeSplitIndex === idx ? '...' : 'Pay'}
                      </Button>
                    ) : (
                      <Badge className="bg-green-100 text-green-700 border-green-300">Paid</Badge>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
          <Button variant="ghost" className="w-full" onClick={onClose}>
            <ChevronLeft size={16} className="mr-1" /> Back to Methods
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** One QR / link per table, for guests to split and pay from their own
 * phones (pages/SplitBillGuest.jsx) — each guest verifies their own phone
 * and pays only their share, rather than one card at the counter for the
 * whole table. */
export function SplitBillLinkDialog({ open, onClose, tableNumber, businessId }) {
  const url = `${window.location.origin}/split/${encodeURIComponent(tableNumber || '')}?business=${encodeURIComponent(businessId || '')}`;
  const copyLink = () => {
    navigator.clipboard?.writeText(url).catch(() => {});
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm" data-testid="split-link-dialog">
        <DialogHeader><DialogTitle>Split via Guest Link</DialogTitle></DialogHeader>
        <div className="flex flex-col items-center py-4 space-y-4">
          <div className="bg-white p-4 rounded-xl shadow-inner border">
            <QRCodeSVG value={url} size={200} level="M" includeMargin />
          </div>
          <p className="text-sm text-gray-500 text-center">
            Table {tableNumber} — guests scan this to pick their items, verify their number by text, and pay their own share.
          </p>
          <div className="flex items-center gap-2 w-full">
            <Input readOnly value={url} className="text-xs font-mono" data-testid="split-link-url" />
            <Button size="icon" variant="outline" onClick={copyLink} data-testid="split-link-copy">
              <Copy size={14} />
            </Button>
          </div>
          <Badge variant="outline" className="text-orange-600 border-orange-300 bg-orange-50">
            <Smartphone size={12} className="mr-1" /> Each guest pays their own share
          </Badge>
          <Button variant="ghost" className="w-full" onClick={onClose}>
            <ChevronLeft size={16} className="mr-1" /> Back to Methods
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
