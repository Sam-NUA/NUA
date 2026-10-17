import React, { useEffect, useState } from 'react';
import { Building2, Check, ShieldCheck, Sparkles, Loader2 } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { useTheme } from '../contexts/ThemeContext';
import { useBusiness } from '../contexts/BusinessContext';
import { businessAPI, licenseAPI } from '../services/api';
import { BUSINESS_TYPE_OPTIONS, VERTICAL_LABELS } from '../lib/businessVertical';
import { toast } from 'sonner';

const VERTICAL_GROUPS = [...new Set(BUSINESS_TYPE_OPTIONS.map(o => o.vertical))];

// Shown once, on first login, for a business that hasn't finished setup
// (business.onboardingComplete !== true). Blocks the whole app shell while
// it's up — there is deliberately no "skip" on the ABN step; per policy
// (see backend/routes/licensing.py) a license binds one verified ABN for
// good, so this is also the one moment that ABN ever gets asked for.
// Vertical, unlike the ABN, stays editable afterward from Multi-Business
// settings — this wizard just picks a sensible starting point.
export default function OnboardingWizard() {
  const { theme } = useTheme();
  const { business, refresh } = useBusiness();
  const [step, setStep] = useState(1);
  const [checkingLicense, setCheckingLicense] = useState(true);

  const [details, setDetails] = useState({ name: '', address: '', phone: '' });
  const [savingDetails, setSavingDetails] = useState(false);

  const [abn, setAbn] = useState('');
  const [abnError, setAbnError] = useState('');
  const [verifyingAbn, setVerifyingAbn] = useState(false);
  const [abnEntityName, setAbnEntityName] = useState('');

  const [selectedType, setSelectedType] = useState('');
  const [savingType, setSavingType] = useState(false);

  const [finishing, setFinishing] = useState(false);

  useEffect(() => {
    if (business) setDetails({ name: business.name || '', address: business.address || '', phone: business.phone || '' });
  }, [business?.id]);  

  // A license may already exist for this tenant (e.g. set up earlier via
  // the License page directly) — don't force a second, blocked ABN step
  // if so, just carry the already-verified entity name forward.
  useEffect(() => {
    licenseAPI.me().then(r => {
      if (r.data?.hasLicense) {
        setAbnEntityName(r.data.abnEntityName || '');
        setAbn(r.data.abn || '');
      }
    }).catch(() => {}).finally(() => setCheckingLicense(false));
  }, []);

  const saveDetails = async () => {
    if (!details.name.trim()) { toast.error('Give the business a name'); return; }
    setSavingDetails(true);
    try {
      await businessAPI.update(business.id, details);
      setStep(2);
    } catch {
      toast.error('Failed to save — try again');
    } finally { setSavingDetails(false); }
  };

  const verifyAbn = async () => {
    setAbnError('');
    setVerifyingAbn(true);
    try {
      const r = await licenseAPI.onboard({ abn, tenantId: business.id, plan: 'standard' });
      setAbnEntityName(r.data.abnEntityName || '');
      toast.success(`ABN verified — ${r.data.abnEntityName || 'entity confirmed'}`);
      setStep(3);
    } catch (e) {
      const detail = e.response?.data?.detail || 'Verification failed — check the ABN and try again.';
      if (e.response?.status === 409) {
        // A license already exists for this tenant (race with another tab,
        // or set up separately) — that's success, not a failure.
        setStep(3);
      } else {
        setAbnError(detail);
      }
    } finally { setVerifyingAbn(false); }
  };

  const saveVertical = async () => {
    if (!selectedType) { toast.error('Pick what best describes the business'); return; }
    setSavingType(true);
    try {
      await businessAPI.update(business.id, { type: selectedType });
      setStep(4);
    } catch {
      toast.error('Failed to save — try again');
    } finally { setSavingType(false); }
  };

  const finish = async () => {
    setFinishing(true);
    try {
      await businessAPI.update(business.id, { onboardingComplete: true });
      refresh();
    } catch {
      toast.error('Failed to finish setup — try again');
      setFinishing(false);
    }
  };

  if (!business) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="animate-spin text-gray-400" size={28} />
      </div>
    );
  }

  const steps = [
    { n: 1, label: 'Business' },
    { n: 2, label: 'ABN' },
    { n: 3, label: 'Type' },
    { n: 4, label: 'Done' },
  ];

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4" data-testid="onboarding-wizard">
      <div className="w-full max-w-lg">
        <div className="flex items-center justify-center gap-2 mb-6">
          {steps.map((s, i) => (
            <React.Fragment key={s.n}>
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step >= s.n ? 'text-white' : 'bg-gray-200 text-gray-400'}`}
                style={step >= s.n ? { backgroundColor: theme.primary } : {}}>
                {step > s.n ? <Check size={13} /> : s.n}
              </div>
              {i < steps.length - 1 && <div className={`w-8 h-0.5 ${step > s.n ? '' : 'bg-gray-200'}`} style={step > s.n ? { backgroundColor: theme.primary } : {}} />}
            </React.Fragment>
          ))}
        </div>

        <div className="bg-white rounded-xl shadow-sm border p-6 space-y-4">
          {step === 1 && (
            <div className="space-y-4" data-testid="wizard-step-details">
              <div className="text-center space-y-1">
                <Building2 className="mx-auto text-gray-400" size={28} />
                <h1 className="text-lg font-bold">Let's set up your business</h1>
                <p className="text-sm text-gray-500">A few quick steps — you'll only see this once.</p>
              </div>
              <Input placeholder="Business name" value={details.name} onChange={e => setDetails({ ...details, name: e.target.value })} data-testid="wizard-name-input" />
              <Input placeholder="Address (optional)" value={details.address} onChange={e => setDetails({ ...details, address: e.target.value })} data-testid="wizard-address-input" />
              <Input placeholder="Phone (optional)" value={details.phone} onChange={e => setDetails({ ...details, phone: e.target.value })} data-testid="wizard-phone-input" />
              <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={saveDetails} disabled={savingDetails} data-testid="wizard-details-next">
                {savingDetails ? 'Saving…' : 'Continue'}
              </Button>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4" data-testid="wizard-step-abn">
              <div className="text-center space-y-1">
                <ShieldCheck className="mx-auto text-gray-400" size={28} />
                <h1 className="text-lg font-bold">Verify your ABN</h1>
                <p className="text-sm text-gray-500">One verified ABN per account, checked live against the Australian Business Register — this can't be changed later without a support review.</p>
              </div>
              {checkingLicense ? (
                <p className="text-sm text-gray-400 text-center py-4">Checking for an existing license…</p>
              ) : abnEntityName ? (
                <div className="text-center py-2">
                  <p className="text-sm text-emerald-700 font-medium flex items-center justify-center gap-1.5"><Check size={15} /> Already verified — {abnEntityName}</p>
                  <Button className="w-full mt-3" style={{ backgroundColor: theme.primary }} onClick={() => setStep(3)} data-testid="wizard-abn-already-verified-next">
                    Continue
                  </Button>
                </div>
              ) : (
                <>
                  <Input placeholder="ABN (11 digits)" value={abn} onChange={e => { setAbn(e.target.value); setAbnError(''); }} data-testid="wizard-abn-input" />
                  {abnError && <p className="text-xs text-red-600" data-testid="wizard-abn-error">{abnError}</p>}
                  <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={verifyAbn} disabled={verifyingAbn || !abn.trim()} data-testid="wizard-abn-verify">
                    {verifyingAbn ? 'Verifying…' : 'Verify & Continue'}
                  </Button>
                </>
              )}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4" data-testid="wizard-step-type">
              <div className="text-center space-y-1">
                <Sparkles className="mx-auto text-gray-400" size={28} />
                <h1 className="text-lg font-bold">What kind of business is this?</h1>
                <p className="text-sm text-gray-500">This shapes the whole app for you — you can change it later in Settings.</p>
              </div>
              <div className="space-y-3">
                {VERTICAL_GROUPS.map(v => (
                  <div key={v}>
                    <p className="text-[11px] font-bold uppercase tracking-widest text-gray-400 mb-1.5">{VERTICAL_LABELS[v]}</p>
                    <div className="grid grid-cols-2 gap-1.5">
                      {BUSINESS_TYPE_OPTIONS.filter(o => o.vertical === v).map(o => (
                        <button key={o.value} type="button" onClick={() => setSelectedType(o.value)}
                          className={`px-3 py-2 text-sm rounded-lg border text-left font-medium transition-colors ${selectedType === o.value ? 'text-white border-transparent' : 'bg-white text-gray-700 border-gray-200 hover:border-gray-400'}`}
                          style={selectedType === o.value ? { backgroundColor: theme.primary } : {}}
                          data-testid={`wizard-type-${o.value}`}>
                          {o.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={saveVertical} disabled={savingType || !selectedType} data-testid="wizard-type-next">
                {savingType ? 'Saving…' : 'Continue'}
              </Button>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4 text-center" data-testid="wizard-step-done">
              <Check className="mx-auto text-emerald-500" size={32} />
              <h1 className="text-lg font-bold">You're all set</h1>
              <p className="text-sm text-gray-500">NUA is configured for your business — let's get started.</p>
              <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={finish} disabled={finishing} data-testid="wizard-finish">
                {finishing ? 'Finishing…' : 'Go to Dashboard'}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
