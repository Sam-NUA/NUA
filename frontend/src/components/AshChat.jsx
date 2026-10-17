import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { Sparkles, Send, X, Minus, Brain, Crown, Calculator, Package, Users, Megaphone, Heart, ChevronDown } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Badge } from './ui/badge';
import { useAuth } from '../contexts/AuthContext';
import { SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

const SESSION_KEY_BASE = 'nua-ash-chat-session';
const userScope = () => {
  try {
    const u = JSON.parse(localStorage.getItem('nua_user') || '{}');
    return u.email || 'anon';
  } catch { return 'anon'; }
};
const SESSION_KEY = () => `${SESSION_KEY_BASE}::${userScope()}`;
const MSGS_KEY = () => `${SESSION_KEY_BASE}::${userScope()}::msgs`;
const PERSONA_KEY = () => `${SESSION_KEY_BASE}::${userScope()}::persona`;

const PERSONA_ICON = {
  executive: Sparkles, finance: Calculator, ops: Package, hr: Users, marketing: Megaphone, guest: Heart,
};

const SUGGESTIONS_BY_PERSONA = {
  executive: [
    'What should I focus on today?',
    'Give me today\u2019s briefing',
    'What did we ship yesterday?',
    'How much did we make this week?',
    'Any approvals waiting on me?',
  ],
  finance: [
    'How did revenue trend this week?',
    'Any journals awaiting approval?',
    'What\u2019s our gross margin?',
  ],
  ops: [
    'Which items are below par?',
    'Any high-waste items to 86?',
    'Create a PO for our top low-stock item',
  ],
  hr: [
    'Any staff at burnout risk?',
    'Create a task for pre-shift briefing',
    'Who is rostered tomorrow?',
  ],
  marketing: [
    'Suggest a promo for slow-moving stock',
    'Which VIPs haven\u2019t visited in 30 days?',
    'Draft an SMS to re-engage lapsed customers',
  ],
  guest: [
    'Who are today\u2019s VIPs?',
    'Anyone with a birthday this week?',
    'Cancel my 7pm reservation for Table 4',
  ],
};

export default function AshChat() {
  const { user, hasPermission } = useAuth();
  const [open, setOpen] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [msgs, setMsgs] = useState(() => JSON.parse(localStorage.getItem(MSGS_KEY()) || '[]'));
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(SESSION_KEY()) || '');
  const [persona, setPersona] = useState(() => localStorage.getItem(PERSONA_KEY()) || 'executive');
  const [personas, setPersonas] = useState([]);
  const [personaMenuOpen, setPersonaMenuOpen] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    H().then(h => axios.get(`${API}/nua/personas`, { headers: h }).then(r => setPersonas(r.data)).catch(() => {}));
  }, []);

  useEffect(() => {
    localStorage.setItem(MSGS_KEY(), JSON.stringify(msgs.slice(-40)));
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs]);

  const currentPersona = personas.find(p => p.id === persona) || { id: 'executive', label: 'Ask NUA', color: '#4f46e5', tagline: '', modules: [] };
  const CurIcon = PERSONA_ICON[currentPersona.id] || Brain;

  const switchPersona = (pid) => {
    setPersona(pid);
    localStorage.setItem(PERSONA_KEY(), pid);
    setPersonaMenuOpen(false);
    // Reset session so grounding is fresh for the new specialist
    setSessionId('');
    localStorage.removeItem(SESSION_KEY());
  };

  const send = async (text) => {
    const trimmed = (text || input).trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setMsgs(m => [...m, { role: 'user', text: trimmed, ts: Date.now(), persona }]);
    setInput('');
    try {
      const r = await axios.post(`${API}/nua/agent`, { message: trimmed, sessionId, persona }, { headers: await H() });
      if (!sessionId) {
        setSessionId(r.data.sessionId);
        localStorage.setItem(SESSION_KEY(), r.data.sessionId);
      }
      setMsgs(m => [...m, {
        role: 'ash',
        text: r.data.reply,
        reasoning: r.data.reasoning,
        toolResults: r.data.toolResults,
        persona: r.data.persona,
        personaLabel: r.data.personaLabel,
        ts: Date.now(),
      }]);
    } catch (e) {
      setMsgs(m => [...m, { role: 'ash', text: 'NUA is unreachable right now. Try again in a moment.', ts: Date.now() }]);
    } finally {
      setBusy(false);
    }
  };

  const clearSession = () => {
    setMsgs([]);
    setSessionId('');
    localStorage.removeItem(SESSION_KEY());
    localStorage.removeItem(MSGS_KEY());
  };

  const suggestions = SUGGESTIONS_BY_PERSONA[persona] || SUGGESTIONS_BY_PERSONA.executive;

  // Owner-only by default — a manager or staff member only sees this once
  // the owner grants the 'ash' permission (Settings > Permissions), same
  // gate the backend enforces on /nua/chat and /nua/agent.
  if (!user || !hasPermission('ash')) return null;

  // FAB when closed
  if (!open) {
    return (
      <button
        onClick={() => { setOpen(true); setMinimized(false); }}
        className="fixed bottom-20 right-5 z-50 h-14 w-14 rounded-full text-white shadow-xl flex items-center justify-center transition-all hover:scale-105"
        style={{ background: currentPersona.color }}
        data-testid="ash-chat-fab"
        aria-label="Ask NUA"
      >
        <CurIcon size={26} />
        <span className="absolute -top-1 -right-1 h-3 w-3 bg-emerald-400 rounded-full ring-2 ring-white animate-pulse" />
      </button>
    );
  }

  return (
    <div
      className={`fixed bottom-5 right-5 z-50 bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col transition-all ${
        minimized ? 'w-72 h-14' : 'w-96 h-[560px]'
      }`}
      data-testid="ash-chat-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 text-white rounded-t-2xl"
        style={{ background: `linear-gradient(to right, ${currentPersona.color}, ${currentPersona.color}dd)` }}>
        <button
          className="flex items-center gap-2 hover:bg-white/10 rounded px-2 py-1 -ml-2 transition"
          onClick={() => setPersonaMenuOpen(o => !o)}
          data-testid="persona-picker-btn"
        >
          <div className="h-8 w-8 bg-white/20 backdrop-blur rounded-full flex items-center justify-center">
            <CurIcon size={16} />
          </div>
          <div className="text-left">
            <p className="font-semibold text-sm flex items-center gap-1">
              {currentPersona.label} <ChevronDown size={12} />
            </p>
            {!minimized && <p className="text-[10px] opacity-80 max-w-[190px] truncate">{currentPersona.tagline}</p>}
          </div>
        </button>
        <div className="flex items-center gap-1">
          <button onClick={() => setMinimized(m => !m)} className="p-1 hover:bg-white/20 rounded" data-testid="ash-chat-minimize">
            <Minus size={14} />
          </button>
          <button onClick={() => setOpen(false)} className="p-1 hover:bg-white/20 rounded" data-testid="ash-chat-close">
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Persona menu overlay */}
      {personaMenuOpen && !minimized && (
        <div className="absolute top-16 left-3 right-3 bg-white shadow-xl border rounded-xl z-10 overflow-hidden" data-testid="persona-menu">
          {personas.map(p => {
            const Icon = PERSONA_ICON[p.id] || Brain;
            return (
              <button
                key={p.id}
                onClick={() => switchPersona(p.id)}
                className={`w-full flex items-start gap-3 px-3 py-2.5 text-left hover:bg-slate-50 border-b last:border-b-0 ${p.id === persona ? 'bg-indigo-50' : ''}`}
                data-testid={`persona-opt-${p.id}`}
              >
                <div className="h-8 w-8 rounded-full flex items-center justify-center text-white flex-shrink-0"
                  style={{ background: p.color }}><Icon size={14} /></div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{p.label}</p>
                  <p className="text-[10px] text-slate-500 truncate">{p.tagline}</p>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {minimized ? null : (
        <>
          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-slate-50" data-testid="ash-chat-messages">
            {msgs.length === 0 && (
              <div className="text-center py-6">
                <Sparkles className="mx-auto mb-2 text-indigo-400" size={28} />
                <p className="text-sm text-slate-600 mb-1">Hi, I&apos;m {currentPersona.label}.</p>
                <p className="text-xs text-slate-500 mb-4">{currentPersona.tagline}</p>
                <div className="space-y-2 text-left">
                  {suggestions.map((s, i) => (
                    <button key={i} onClick={() => send(s)} className="w-full text-left text-xs px-3 py-2 rounded-lg bg-white border hover:border-indigo-300 hover:bg-indigo-50 transition"
                      data-testid={`ash-suggest-${i}`}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${
                  m.role === 'user' ? 'text-white' : 'bg-white border shadow-sm'
                }`}
                  style={m.role === 'user' ? { background: currentPersona.color } : {}}
                  data-testid={`msg-${m.role}-${i}`}>
                  {m.role === 'ash' && m.personaLabel && (
                    <p className="text-[9px] uppercase tracking-wider text-slate-400 mb-1">{m.personaLabel}</p>
                  )}
                  <p className="whitespace-pre-wrap">{m.text}</p>
                  {(m.toolResults && m.toolResults.length > 0) && (
                    <div className="mt-2 pt-2 border-t border-slate-100 space-y-1">
                      {m.toolResults.map((t, ix) => (
                        <div key={ix} className="text-[10px] flex items-center gap-1">
                          <Badge className={
                            t.status === 'executed' ? 'bg-emerald-500' :
                            t.status === 'pending_approval' ? 'bg-amber-500' :
                            t.status === 'blocked' ? 'bg-rose-500' : 'bg-slate-500'
                          }>{t.status.replace('_', ' ')}</Badge>
                          <span className="font-mono text-slate-600">{t.tool}</span>
                          {t.approvalId && <span className="text-slate-400">approval {t.approvalId.slice(0, 6)}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                  {m.reasoning && (
                    <details className="mt-2 pt-2 border-t border-slate-100 text-[10px] cursor-pointer text-slate-500">
                      <summary className="font-medium">Why · confidence {Math.round((m.reasoning.confidence || 0) * 100)}%</summary>
                      <div className="mt-1 space-y-1 whitespace-pre-wrap">
                        {m.reasoning.problem && <p><b>Problem:</b> {m.reasoning.problem}</p>}
                        {m.reasoning.evidence && <p><b>Evidence:</b> {m.reasoning.evidence}</p>}
                        {m.reasoning.alternatives && <p><b>Alternatives:</b> {Array.isArray(m.reasoning.alternatives) ? m.reasoning.alternatives.join(', ') : m.reasoning.alternatives}</p>}
                        {m.reasoning.risk && <p><b>Risk:</b> {m.reasoning.risk}</p>}
                        {m.reasoning.expectedImpact && <p><b>Impact:</b> {m.reasoning.expectedImpact}</p>}
                        {m.reasoning.rollback && <p><b>Rollback:</b> {m.reasoning.rollback}</p>}
                      </div>
                    </details>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="flex justify-start">
                <div className="bg-white border rounded-2xl px-3 py-2 text-sm text-slate-500 flex items-center gap-2 shadow-sm">
                  <span className="animate-pulse">{currentPersona.label} is thinking&hellip;</span>
                </div>
              </div>
            )}
          </div>

          {/* Composer */}
          <div className="px-3 py-2 border-t flex items-center gap-2 bg-white rounded-b-2xl">
            <Input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={`Ask ${currentPersona.label}\u2026`}
              className="flex-1 text-sm"
              disabled={busy}
              data-testid="ash-chat-input"
            />
            <Button size="sm" onClick={() => send()} disabled={busy || !input.trim()} className="shrink-0" data-testid="ash-chat-send">
              <Send size={14} />
            </Button>
          </div>
          {msgs.length > 0 && (
            <button onClick={clearSession} className="text-[10px] text-slate-400 hover:text-rose-500 pb-1" data-testid="ash-chat-reset">
              Reset conversation
            </button>
          )}
        </>
      )}
    </div>
  );
}
