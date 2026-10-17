import React, { useEffect, useState } from 'react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';
import { finalizeAPI } from '../../services/api';
import { FileText, RefreshCcw, Download } from 'lucide-react';
import { FileService } from '../../platform';

/** ATO-labelled BAS Worksheet for a period range. Renders G1-G20 + W1-W5 + T1. */
export default function BasWorksheetPanel({ theme }) {
  const q = new Date();
  const qm = Math.floor(q.getMonth() / 3) * 3;
  const [start, setStart] = useState(new Date(q.getFullYear(), qm, 1).toISOString().slice(0, 10));
  const [end, setEnd] = useState(new Date(q.getFullYear(), qm + 3, 0).toISOString().slice(0, 10));
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      const r = await finalizeAPI.basWorksheet(start, end);
      setData(r.data);
    } catch { /* silent */ }
    finally { setBusy(false); }
  };
  useEffect(() => { load(); }, []); // load on mount only

  const exportCsv = async () => {
    if (!data) return;
    const rows = [
      ['Label', 'Description', 'Amount ($)'],
      ...Object.entries(data.sales || {}).map(([k, v]) => [k.split('_')[0], k.replace(/^G\d+_/, '').replace(/([A-Z])/g, ' $1').trim(), (v || 0).toFixed(2)]),
      ...Object.entries(data.acquisitions || {}).map(([k, v]) => [k.split('_')[0], k.replace(/^G\d+_/, '').replace(/([A-Z])/g, ' $1').trim(), (v || 0).toFixed(2)]),
      ...Object.entries(data.withholding || {}).map(([k, v]) => [k.split('_')[0], k.replace(/^W\d+_/, '').replace(/([A-Z])/g, ' $1').trim(), (v || 0).toFixed(2)]),
      ['T1', 'PAYG Instalment', (data.instalment?.T1_paygInstalment || 0).toFixed(2)],
      ['NET_GST', 'Net GST', (data.netGST || 0).toFixed(2)],
    ];
    const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
    await FileService.downloadFile(new Blob([csv], { type: 'text/csv' }), `BAS-${start}-to-${end}.csv`);
  };

  const row = (code, label, val, opts = {}) => (
    <div className={`flex items-center justify-between text-sm py-1 ${opts.bold ? 'font-semibold border-t' : ''}`} data-testid={`bas-${code}`}>
      <span className="text-gray-500 mr-2 font-mono text-xs w-8">{code}</span>
      <span className="flex-1 truncate">{label}</span>
      <span className="font-mono">${(val || 0).toFixed(2)}</span>
    </div>
  );

  return (
    <Card className="border-0 shadow-sm">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <FileText size={16} style={{ color: theme?.primary || '#f97316' }} />
            <h3 className="font-semibold">ATO BAS Worksheet</h3>
            <Badge className="bg-blue-100 text-blue-700 border-0 text-[10px]">NAT 4189</Badge>
          </div>
          <div className="flex items-center gap-2">
            <Input type="date" value={start} onChange={e => setStart(e.target.value)} className="w-40 h-8" data-testid="bas-start" />
            <span className="text-xs text-gray-400">→</span>
            <Input type="date" value={end} onChange={e => setEnd(e.target.value)} className="w-40 h-8" data-testid="bas-end" />
            <Button size="sm" variant="outline" onClick={load} disabled={busy} data-testid="bas-refresh">
              <RefreshCcw size={12} className={`mr-1 ${busy ? 'animate-spin' : ''}`} /> Refresh
            </Button>
            <Button size="sm" variant="outline" onClick={exportCsv} disabled={!data} data-testid="bas-export">
              <Download size={12} className="mr-1" /> CSV
            </Button>
          </div>
        </div>
        {data ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 pt-2">
            <div>
              <p className="text-[10px] uppercase tracking-widest font-semibold text-gray-500 mb-1">Sales & GST on sales</p>
              {row('G1', 'Total sales (incl. GST)', data.sales?.G1_totalSales)}
              {row('G2', 'Exports', data.sales?.G2_exports)}
              {row('G3', 'GST-free sales', data.sales?.G3_gstFreeSales)}
              {row('G4', 'Input-taxed sales', data.sales?.G4_inputTaxedSales)}
              {row('G5', 'Subtotal', data.sales?.G5_subtotal)}
              {row('G6', 'Taxable supplies', data.sales?.G6_taxableSupplies)}
              {row('G7', 'Adjustments', data.sales?.G7_adjustments)}
              {row('G8', 'Total', data.sales?.G8_total, { bold: true })}
              {row('1A', 'GST on sales', data.sales?.G9_gstOnSales_1A, { bold: true })}
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-widest font-semibold text-gray-500 mb-1">Purchases & GST credits</p>
              {row('G10', 'Capital purchases', data.acquisitions?.G10_capital)}
              {row('G11', 'Non-capital purchases', data.acquisitions?.G11_nonCapital)}
              {row('G12', 'Subtotal', data.acquisitions?.G12_subtotal)}
              {row('G13', 'Input taxed', data.acquisitions?.G13_inputTaxed)}
              {row('G14', 'Private use', data.acquisitions?.G14_private)}
              {row('G15', 'GST-free purchases', data.acquisitions?.G15_estimateGstFree)}
              {row('G16', 'Subtotal', data.acquisitions?.G16_subtotal)}
              {row('G17', 'Creditable', data.acquisitions?.G17_creditable, { bold: true })}
              {row('1B', 'GST on purchases', data.acquisitions?.G20_gstOnPurchases_1B, { bold: true })}
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-widest font-semibold text-gray-500 mb-1">Withholding + Instalment</p>
              {row('W1', 'Total gross wages', data.withholding?.W1_totalWages)}
              {row('W2', 'PAYG withheld', data.withholding?.W2_paygWithheld)}
              {row('W3', 'No-ABN withholding', data.withholding?.W3_noAbnWithholding)}
              {row('W4', 'Other withholding', data.withholding?.W4_otherWithholding)}
              {row('W5', 'Total withheld', data.withholding?.W5_totalWithheld, { bold: true })}
              {row('T1', 'PAYG instalment', data.instalment?.T1_paygInstalment, { bold: true })}
              <div className="mt-3 rounded-lg p-3 border-2" style={{ borderColor: theme?.primary || '#f97316' }} data-testid="bas-summary">
                <p className="text-[10px] uppercase tracking-widest font-semibold text-gray-500">Summary</p>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-sm">Net GST</span>
                  <span className="font-mono font-bold" style={{ color: (data.netGST || 0) >= 0 ? '#ef4444' : '#10b981' }}>${(data.netGST || 0).toFixed(2)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm">Total owing to ATO</span>
                  <span className="font-mono font-bold text-lg" style={{ color: '#dc2626' }} data-testid="bas-total-owing">${(data.summary?.totalOwing || 0).toFixed(2)}</span>
                </div>
                {(data.summary?.refundDue || 0) > 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Refund due</span>
                    <span className="font-mono font-bold text-lg text-emerald-600">${(data.summary.refundDue).toFixed(2)}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <p className="text-xs text-gray-400 italic">Loading worksheet…</p>
        )}
      </CardContent>
    </Card>
  );
}
