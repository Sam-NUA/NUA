import React, { useState } from 'react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { useTheme } from '../../contexts/ThemeContext';
import { backupAPI } from '../../services/api';
import { toast } from 'sonner';
import { DownloadCloud, ShieldQuestion, CheckCircle2, XCircle } from 'lucide-react';

/**
 * An untested backup isn't a backup — it's a file nobody has opened since
 * the day it was written. "Run restore drill" doesn't just say a backup
 * exists; it actually restores one into a disposable scratch database and
 * reports whether every collection came back with the right document count.
 */
export default function BackupPanel() {
  const { theme } = useTheme();
  const [downloading, setDownloading] = useState(false);
  const [drilling, setDrilling] = useState(false);
  const [drill, setDrill] = useState(null);

  const download = async () => {
    setDownloading(true);
    try {
      const r = await backupAPI.download();
      const url = URL.createObjectURL(new Blob([r.data], { type: 'application/gzip' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `nua-backup-${new Date().toISOString().slice(0, 10)}.tar.gz`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('Backup downloaded');
    } catch (e) { toast.error(e.response?.data?.detail || 'Backup failed'); }
    setDownloading(false);
  };

  const runDrill = async () => {
    setDrilling(true);
    try { setDrill((await backupAPI.runDrill()).data); }
    catch (e) { toast.error(e.response?.data?.detail || 'Drill failed to run'); }
    setDrilling(false);
  };

  const card = { backgroundColor: theme.cardBg || theme.background, color: theme.text };

  return (
    <div className="space-y-4" data-testid="backup-panel">
      <Card style={card}>
        <CardContent className="p-6 space-y-4">
          <div className="flex items-center gap-3">
            <DownloadCloud size={22} style={{ color: theme.primary }} />
            <div>
              <h3 className="font-bold text-lg">Backup</h3>
              <p className="text-sm opacity-70">
                Every product, customer, transaction and setting, as a single downloadable file.
              </p>
            </div>
          </div>
          <Button onClick={download} disabled={downloading} data-testid="backup-download">
            {downloading ? 'Preparing…' : 'Download backup now'}
          </Button>
        </CardContent>
      </Card>

      <Card style={card}>
        <CardContent className="p-6 space-y-4">
          <div className="flex items-center gap-3">
            <ShieldQuestion size={22} className={drill?.ok ? 'text-green-500' : 'text-amber-500'} />
            <div>
              <h3 className="font-bold text-lg">Restore drill</h3>
              <p className="text-sm opacity-70">
                Actually restores today's data into a throwaway test database and checks it
                matches — your live data is never touched.
              </p>
            </div>
          </div>
          <Button onClick={runDrill} disabled={drilling} data-testid="backup-drill">
            {drilling ? 'Running drill…' : 'Run restore drill'}
          </Button>

          {drill && (
            <div className="space-y-2 pt-2" data-testid="backup-drill-result">
              <div className="flex items-center gap-2 text-sm font-medium">
                {drill.ok
                  ? <><CheckCircle2 size={16} className="text-green-500" /> Restore verified — everything matches</>
                  : <><XCircle size={16} className="text-red-500" /> Something didn't match</>}
              </div>
              {(drill.archiveProblems || []).length > 0 && (
                <ul className="text-sm text-red-500 list-disc pl-5">
                  {drill.archiveProblems.map((p, i) => <li key={i}>{p}</li>)}
                </ul>
              )}
              {drill.collections && (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                  {Object.entries(drill.collections).map(([name, c]) => (
                    <div key={name} className="rounded-lg p-2 flex items-center justify-between"
                         style={{ backgroundColor: theme.background }}>
                      <span>{name}</span>
                      <span className={c.matches ? 'text-green-500' : 'text-red-500'}>
                        {c.restoredCount}/{c.archiveCount ?? c.liveCount}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
