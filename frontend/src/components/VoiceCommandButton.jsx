import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Mic, Square, Loader2 } from 'lucide-react';
import { agentAPI } from '../services/api';
import { toast } from 'sonner';

/**
 * Always-visible global voice command mic — what AgentDashboard's own
 * tagline ("Voice commands work everywhere via the mic") actually refers
 * to. Records a short utterance, sends it to POST /agent/voice-command
 * (routes/loyalty_engine.py), which transcribes it and classifies it into
 * an intent via LLM, and executes what a page-independent component
 * honestly can:
 *   - navigate / run_report / book_reservation → real navigation (a
 *     reservation preset rides along as router state for /reservations
 *     to pick up if it wants it; ignored harmlessly if not).
 *   - agent_tick → actually runs the agent cycle, same as the "Run Cycle"
 *     button on the Agent page.
 *   - add_item / redeem_points / message_blast → these need context this
 *     floating button doesn't have (an open sale, a selected customer, a
 *     draft campaign), so it navigates to where that context lives and
 *     says so — never silently drops the command or pretends it acted.
 *   - unknown → surfaces the transcript so the user can see what was
 *     actually heard.
 */
export default function VoiceCommandButton() {
  const [recording, setRecording] = useState(false);
  const [processing, setProcessing] = useState(false);
  const mediaRef = useRef(null);
  const chunksRef = useRef([]);
  const navigate = useNavigate();

  const runInstruction = async ({ transcript, intent, parsed, instruction }) => {
    const instr = instruction || {};
    if (instr.navigate) {
      navigate(instr.navigate, instr.preset ? { state: { voicePreset: instr.preset } } : undefined);
      toast.success(`"${transcript}" — heading to ${instr.navigate}`);
      return;
    }
    switch (instr.action) {
      case 'agent_tick': {
        try {
          const r = await agentAPI.tick();
          toast.success(`Agent cycle run — ${r.data?.decisionsCount || 0} new decision(s)`);
        } catch {
          toast.error('Agent cycle failed to run');
        }
        return;
      }
      case 'add_to_cart':
        navigate('/pos');
        toast(`Heard "${transcript}" — say it again on the POS screen to add it to a sale`);
        return;
      case 'redeem_points':
        navigate('/pos');
        toast('Redeeming points needs a customer selected at checkout — pick them up on the POS screen');
        return;
      case 'open_blast': {
        const audience = parsed?.args?.audience;
        navigate(audience ? `/marketing?tab=loyalty&audience=${encodeURIComponent(audience)}` : '/marketing?tab=loyalty');
        toast.success(`"${transcript}" — opening Marketing to send that`);
        return;
      }
      default:
        toast(intent && intent !== 'unknown'
          ? `Heard "${transcript}" but couldn't find an action for it yet`
          : `Heard "${transcript}" — not sure what to do with that`);
    }
  };

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => chunksRef.current.push(e.data);
      mr.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        stream.getTracks().forEach((t) => t.stop());
        setProcessing(true);
        try {
          const reader = new FileReader();
          reader.onloadend = async () => {
            try {
              const r = await agentAPI.voiceCommand(reader.result, 'audio/webm');
              if (r.data?.error) {
                toast.error(`Voice command failed: ${r.data.error}`);
              } else {
                await runInstruction(r.data || {});
              }
            } catch {
              toast.error('Voice command failed');
            }
            setProcessing(false);
          };
          reader.readAsDataURL(blob);
        } catch {
          setProcessing(false);
        }
      };
      mr.start();
      mediaRef.current = mr;
      setRecording(true);
    } catch {
      toast.error('Microphone access denied');
    }
  };

  const stop = () => {
    if (mediaRef.current && mediaRef.current.state === 'recording') {
      mediaRef.current.stop();
      setRecording(false);
    }
  };

  return (
    <button
      onClick={recording ? stop : start}
      disabled={processing}
      title="Voice command — say a page name, 'run agent cycle', 'show today's revenue'…"
      data-testid="global-voice-command-btn"
      className={`fixed bottom-20 right-40 z-40 h-12 w-12 rounded-full shadow-lg border flex items-center justify-center transition
        ${recording ? 'bg-red-50 border-red-300 text-red-600 animate-pulse' : 'bg-white hover:bg-slate-50 text-slate-600'}`}
    >
      {processing ? <Loader2 size={18} className="animate-spin" /> : recording ? <Square size={16} /> : <Mic size={18} />}
    </button>
  );
}
