import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useTheme } from '../contexts/ThemeContext';
import { finalizeAPI } from '../services/api';
import { toast } from 'sonner';
import { DollarSign, Users, FileText, Calculator, Send, Download, Shield, Calendar, TrendingUp, AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { FileService } from '../platform';

const monday = () => {
  const d = new Date();
  const day = d.getDay(); // 0 Sun … 6 Sat
  const diff = (day === 0 ? -6 : 1 - day);
  d.setDate(d.getDate() + diff);
  return d.toISOString().slice(0, 10);
};
const sunday = () => {
  const d = new Date(monday());
  d.setDate(d.getDate() + 6);
  return d.toISOString().slice(0, 10);
};

export default function Payroll() {
  const { theme } = useTheme();
  const [tab, setTab] = useState('payrun');
  const [form, setForm] = useState({
    periodStart: monday(), periodEnd: sunday(),
    payDate: sunday(), period: 'week',
  });
  const [calc, setCalc] = useState(null);
  const [busy, setBusy] = useState(false);
  const [register, setRegister] = useState({ runs: [], totals: {} });
  const [compliance, setCompliance] = useState(null);
  const [committing, setCommitting] = useState(false);
  const [expandedRun, setExpandedRun] = useState(null);
  const [downloadingPayslip, setDownloadingPayslip] = useState(null); // `${runId}-${staffId}`
  const [ytdFor, setYtdFor] = useState(null); // staffId currently showing YTD
  const [ytdData, setYtdData] = useState({}); // staffId -> summary (cached across toggles)
  const [ytdLoading, setYtdLoading] = useState(null); // staffId

  const runCalc = async () => {
    setBusy(true);
    try {
      const r = await finalizeAPI.payrunCalculate(form);
      setCalc(r.data);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Calc failed'); }
    finally { setBusy(false); }
  };

  const commitRun = async () => {
    if (!calc) return;
    setCommitting(true);
    try {
      const r = await finalizeAPI.payrunCommit(calc);
      toast.success(`Pay run committed · ${r.data.runId}`);
      setCalc(null);
      loadRegister();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Commit failed'); }
    finally { setCommitting(false); }
  };

  const loadRegister = async () => {
    try {
      const r = await finalizeAPI.payrollRegister(90);
      setRegister(r.data);
    } catch { /* silent */ }
  };
  const loadCompliance = async () => {
    try {
      const r = await finalizeAPI.rosterCompliance(14);
      setCompliance(r.data);
    } catch { /* silent */ }
  };
  useEffect(() => { loadRegister(); loadCompliance(); }, []);

  const downloadPayslip = async (runId, staffId, staffName) => {
    const key = `${runId}-${staffId}`;
    setDownloadingPayslip(key);
    try {
      const r = await finalizeAPI.payslipPdf(runId, staffId);
      await FileService.downloadFile(new Blob([r.data], { type: 'application/pdf' }), `payslip-${staffName || staffId}-${runId}.pdf`);
    } catch { toast.error('Payslip download failed'); }
    finally { setDownloadingPayslip(null); }
  };

  const toggleYtd = async (staffId) => {
    if (ytdFor === staffId) { setYtdFor(null); return; }
    setYtdFor(staffId);
    if (ytdData[staffId]) return; // cached from an earlier toggle this session
    setYtdLoading(staffId);
    try {
      const r = await finalizeAPI.payrollYtd(staffId);
      setYtdData(prev => ({ ...prev, [staffId]: r.data }));
    } catch { toast.error('Failed to load year-to-date figures'); setYtdFor(null); }
    finally { setYtdLoading(null); }
  };

  const totalGross = useMemo(() => calc?.totals?.grossPay || 0, [calc]);
  const totalTax = useMemo(() => calc?.totals?.payg || 0, [calc]);
  const totalSuper = useMemo(() => calc?.totals?.super || 0, [calc]);
  const totalNet = useMemo(() => calc?.totals?.netPay || 0, [calc]);

  return (
    <div className="space-y-6" data-testid="payroll-page">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
          <Calculator style={{ color: theme.primary }} /> Payroll
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          ATO Schedule 1 PAYG · Super Guarantee (tiered, OTE) · Fair Work-compliant payslips · STP2 ready
        </p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="payrun" data-testid="tab-payrun">Pay Run</TabsTrigger>
          <TabsTrigger value="register" data-testid="tab-register">Register</TabsTrigger>
          <TabsTrigger value="compliance" data-testid="tab-compliance">Roster Compliance</TabsTrigger>
        </TabsList>

        <TabsContent value="payrun" className="space-y-4 mt-4">
          <Card className="border-0 shadow-sm">
            <CardContent className="p-5 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">Period start</label>
                  <Input type="date" value={form.periodStart}
                    onChange={e => setForm({ ...form, periodStart: e.target.value })}
                    data-testid="pr-period-start" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">Period end</label>
                  <Input type="date" value={form.periodEnd}
                    onChange={e => setForm({ ...form, periodEnd: e.target.value })}
                    data-testid="pr-period-end" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">Pay date</label>
                  <Input type="date" value={form.payDate}
                    onChange={e => setForm({ ...form, payDate: e.target.value })}
                    data-testid="pr-pay-date" />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">Period</label>
                  <Select value={form.period} onValueChange={v => setForm({ ...form, period: v })}>
                    <SelectTrigger data-testid="pr-period"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="week">Weekly</SelectItem>
                      <SelectItem value="fortnight">Fortnightly</SelectItem>
                      <SelectItem value="monthly">Monthly</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex gap-2">
                <Button onClick={runCalc} disabled={busy} style={{ background: theme.primary }} className="text-white" data-testid="pr-calc-btn">
                  <Calculator size={14} className="mr-1.5" /> {busy ? 'Calculating…' : 'Calculate Pay Run'}
                </Button>
                {calc && (
                  <Button onClick={commitRun} disabled={committing} variant="outline" data-testid="pr-commit-btn">
                    <Send size={14} className="mr-1.5" /> {committing ? 'Committing…' : 'Commit + Build STP2'}
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          {calc && (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                  { label: 'Gross Pay', val: totalGross, icon: DollarSign, color: theme.primary },
                  { label: 'PAYG Withheld', val: totalTax, icon: Shield, color: '#ef4444' },
                  { label: 'Super Guarantee', val: totalSuper, icon: TrendingUp, color: '#10b981' },
                  { label: 'Net Pay', val: totalNet, icon: Users, color: theme.accent },
                ].map((s, i) => {
                  const Icon = s.icon;
                  return (
                    <Card key={i} className="border-0 shadow-sm">
                      <CardContent className="p-4 flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: `${s.color}15` }}>
                          <Icon size={18} style={{ color: s.color }} />
                        </div>
                        <div>
                          <p className="text-2xl font-bold" style={{ color: theme.text }}>${(s.val || 0).toFixed(2)}</p>
                          <p className="text-xs text-gray-500">{s.label}</p>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>

              <Card className="border-0 shadow-sm">
                <CardContent className="p-0">
                  <div className="flex items-center justify-between p-4 border-b">
                    <h3 className="font-semibold">Pay run rows ({calc.rows?.length || 0})</h3>
                    <div className="flex items-center gap-3 text-[11px] text-gray-500">
                      <Badge className="bg-blue-100 text-blue-700 border-0">PAYG · {calc.compliance?.paygScheduleVersion}</Badge>
                      <Badge className="bg-emerald-100 text-emerald-700 border-0">SG {calc.compliance?.sgRate}%</Badge>
                      <Badge className="bg-amber-100 text-amber-700 border-0">Super due {calc.compliance?.superDueBy}</Badge>
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm" data-testid="payrun-rows">
                      <thead className="text-xs uppercase tracking-widest text-gray-500 bg-gray-50">
                        <tr>
                          <th className="p-2 text-left">Employee</th>
                          <th className="p-2 text-right">Hours</th>
                          <th className="p-2 text-right">Rate</th>
                          <th className="p-2 text-right">Gross</th>
                          <th className="p-2 text-right">PAYG</th>
                          <th className="p-2 text-right">Super</th>
                          <th className="p-2 text-right">Net</th>
                          <th className="p-2 text-left">Leave (ann/pers)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(calc.rows || []).map((r, i) => (
                          <tr key={i} className="border-t" data-testid={`payrun-row-${r.staffId}`}>
                            <td className="p-2">
                              <p className="font-medium">{r.name}</p>
                              <p className="text-[10px] text-gray-500">{r.role} · {r.employmentType} · Sch {r.paygScale}</p>
                            </td>
                            <td className="p-2 text-right font-mono">{(r.hoursWorked || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono">${(r.baseHourly || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono font-semibold">${(r.grossPay || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono text-red-600">${(r.payg || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono text-emerald-700">${(r.super || 0).toFixed(2)}</td>
                            <td className="p-2 text-right font-mono font-bold">${(r.netPay || 0).toFixed(2)}</td>
                            <td className="p-2 text-[11px] text-gray-500">
                              +{(r.leaveAccrual?.annual || 0).toFixed(2)}h / +{(r.leaveAccrual?.personal || 0).toFixed(2)}h
                            </td>
                          </tr>
                        ))}
                        {(calc.rows || []).length === 0 && (
                          <tr><td colSpan={8} className="p-6 text-center text-sm text-gray-400">
                            No employees with timecards in this window.
                          </td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>

        <TabsContent value="register" className="space-y-4 mt-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              { label: 'Gross (90d)', val: register.totals?.grossPay },
              { label: 'PAYG (90d)', val: register.totals?.payg },
              { label: 'Super (90d)', val: register.totals?.super },
              { label: 'Net (90d)', val: register.totals?.netPay },
            ].map((s, i) => (
              <Card key={i} className="border-0 shadow-sm">
                <CardContent className="p-4">
                  <p className="text-xs text-gray-500 uppercase tracking-widest">{s.label}</p>
                  <p className="text-2xl font-bold mt-1">${(s.val || 0).toFixed(2)}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <Card className="border-0 shadow-sm">
            <CardContent className="p-0">
              <div className="p-4 border-b flex items-center justify-between">
                <h3 className="font-semibold">Committed pay runs ({register.runs?.length || 0})</h3>
                <Badge className="bg-gray-100 text-gray-600 border-0">Last 90 days</Badge>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs uppercase tracking-widest text-gray-500 bg-gray-50">
                    <tr>
                      <th className="p-2 w-6"></th>
                      <th className="p-2 text-left">Run ID</th>
                      <th className="p-2 text-left">Period</th>
                      <th className="p-2 text-left">Pay date</th>
                      <th className="p-2 text-right">Gross</th>
                      <th className="p-2 text-right">PAYG</th>
                      <th className="p-2 text-right">Super</th>
                      <th className="p-2 text-right">Net</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(register.runs || []).map(r => (
                      <React.Fragment key={r.id}>
                        <tr className="border-t cursor-pointer hover:bg-gray-50" data-testid={`register-row-${r.id}`}
                          onClick={() => setExpandedRun(expandedRun === r.id ? null : r.id)}>
                          <td className="p-2 text-gray-400">
                            {expandedRun === r.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </td>
                          <td className="p-2 font-mono text-xs">{r.id}</td>
                          <td className="p-2 text-xs">{r.periodStart} → {r.periodEnd}</td>
                          <td className="p-2 text-xs">{r.payDate}</td>
                          <td className="p-2 text-right font-mono">${(r.totals?.grossPay || 0).toFixed(2)}</td>
                          <td className="p-2 text-right font-mono text-red-600">${(r.totals?.payg || 0).toFixed(2)}</td>
                          <td className="p-2 text-right font-mono text-emerald-700">${(r.totals?.super || 0).toFixed(2)}</td>
                          <td className="p-2 text-right font-mono font-bold">${(r.totals?.netPay || 0).toFixed(2)}</td>
                        </tr>
                        {expandedRun === r.id && (
                          <tr className="border-t bg-gray-50/50">
                            <td colSpan={8} className="p-3">
                              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                                Payslips — {(r.rows || []).length} employee{(r.rows || []).length === 1 ? '' : 's'}
                              </p>
                              <div className="space-y-1" data-testid={`run-payslips-${r.id}`}>
                                {(r.rows || []).map(row => {
                                  const key = `${r.id}-${row.staffId}`;
                                  const ytd = ytdData[row.staffId];
                                  return (
                                    <div key={row.staffId} className="bg-white border rounded-lg px-3 py-1.5">
                                      <div className="flex items-center justify-between">
                                        <span className="text-xs font-medium">{row.name}</span>
                                        <span className="text-xs font-mono text-gray-500">${(row.netPay || 0).toFixed(2)} net</span>
                                        <div className="flex gap-1.5">
                                          <Button size="sm" variant="ghost" className="h-7 text-xs"
                                            disabled={ytdLoading === row.staffId}
                                            onClick={() => toggleYtd(row.staffId)}
                                            data-testid={`toggle-ytd-${row.staffId}`}>
                                            <TrendingUp size={12} className="mr-1" />
                                            {ytdLoading === row.staffId ? 'Loading…' : (ytdFor === row.staffId ? 'Hide YTD' : 'YTD')}
                                          </Button>
                                          <Button size="sm" variant="outline" className="h-7 text-xs"
                                            disabled={downloadingPayslip === key}
                                            onClick={() => downloadPayslip(r.id, row.staffId, row.name)}
                                            data-testid={`download-payslip-${row.staffId}`}>
                                            <Download size={12} className="mr-1" />
                                            {downloadingPayslip === key ? 'Downloading…' : 'Payslip PDF'}
                                          </Button>
                                        </div>
                                      </div>
                                      {ytdFor === row.staffId && ytd && (
                                        <div className="mt-2 pt-2 border-t grid grid-cols-5 gap-2 text-center" data-testid={`ytd-${row.staffId}`}>
                                          <div><p className="text-[10px] text-gray-400 uppercase">Since</p><p className="text-xs font-medium">{ytd.financialYearStart}</p></div>
                                          <div><p className="text-[10px] text-gray-400 uppercase">Gross</p><p className="text-xs font-mono font-semibold">${ytd.grossPay.toFixed(2)}</p></div>
                                          <div><p className="text-[10px] text-gray-400 uppercase">PAYG</p><p className="text-xs font-mono text-red-600">${ytd.payg.toFixed(2)}</p></div>
                                          <div><p className="text-[10px] text-gray-400 uppercase">Super</p><p className="text-xs font-mono text-emerald-700">${ytd.super.toFixed(2)}</p></div>
                                          <div><p className="text-[10px] text-gray-400 uppercase">Runs</p><p className="text-xs font-medium">{ytd.runCount}</p></div>
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                                {(r.rows || []).length === 0 && (
                                  <p className="text-xs text-gray-400">No per-employee rows recorded for this run.</p>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                    {(register.runs || []).length === 0 && (
                      <tr><td colSpan={8} className="p-6 text-center text-sm text-gray-400">No committed runs yet.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="compliance" className="space-y-4 mt-4">
          <Card className="border-0 shadow-sm">
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="font-semibold flex items-center gap-2">
                    <Shield size={16} style={{ color: theme.primary }} /> Roster compliance
                  </h3>
                  <p className="text-xs text-gray-500">Fair Work + Modern Award violations for the next {compliance?.windowDays || 14} days.</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge className="bg-gray-100 text-gray-700 border-0" data-testid="roster-scanned">
                    <Calendar size={11} className="mr-1" /> {compliance?.shiftsScanned || 0} shifts scanned
                  </Badge>
                  <Badge className={`border-0 ${compliance?.flaggedCount ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`} data-testid="roster-flagged">
                    <AlertTriangle size={11} className="mr-1" /> {compliance?.flaggedCount || 0} flagged
                  </Badge>
                </div>
              </div>
              {(compliance?.flagged || []).length === 0 ? (
                <div className="rounded-lg bg-emerald-50 border border-emerald-100 p-4 text-sm text-emerald-800">
                  All rostered shifts comply with the current Modern Award. ✓
                </div>
              ) : (
                <ul className="space-y-2">
                  {(compliance?.flagged || []).map((s, i) => (
                    <li key={i} className="border rounded-lg p-3" data-testid={`flagged-shift-${i}`}>
                      <p className="text-sm font-medium">{s.staffName || s.staffId} · {(s.start || '').slice(0, 16)} → {(s.end || '').slice(0, 16)}</p>
                      <ul className="mt-1 space-y-0.5">
                        {(s.issues || []).map((iss, j) => (
                          <li key={j} className="text-xs flex items-start gap-1.5">
                            <Badge className={`border-0 text-[10px] ${iss.severity === 'high' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>
                              {iss.code}
                            </Badge>
                            <span className="text-gray-600">{iss.message}</span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
