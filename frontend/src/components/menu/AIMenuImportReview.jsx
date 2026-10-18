import React, { useState, useMemo } from 'react';
import { Loader2, Upload, CheckCircle2, XCircle, AlertTriangle, Sparkles, ChevronLeft } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../ui/dialog';
import { menuFeaturesAPI } from '../../services/api';
import { toast } from 'sonner';

/**
 * Two-step AI menu import.
 *   1. Upload → /menu/ai-preview (extract + fuzzy-match categories + suggest modifiers)
 *   2. Review table (edit name/category/price/cost, toggle include, tick modifiers)
 *   3. Commit → /menu/ai-commit (bulk create with stamped_insert)
 */
export default function AIMenuImportReview({ open, onOpenChange, onCommitted }) {
  const [stage, setStage] = useState('upload'); // upload | review | done
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState([]);
  const [knownCats, setKnownCats] = useState([]);
  const [knownMods, setKnownMods] = useState([]);
  const [rawResponse, setRawResponse] = useState(null);
  const [committing, setCommitting] = useState(false);
  const [menuText, setMenuText] = useState('');

  const reset = () => {
    setStage('upload'); setItems([]); setKnownCats([]); setKnownMods([]);
    setRawResponse(null); setLoading(false); setCommitting(false); setMenuText('');
  };

  const handleClose = (v) => {
    if (!v) reset();
    onOpenChange?.(v);
  };

  const handleFileUpload = async (e) => {
    const input = e.target;
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > 3_000_000) {
      toast.error('Choose a menu file under 3 MB. Split larger PDFs into fewer pages or use a smaller photo.');
      input.value = '';
      return;
    }
    setLoading(true);
    setRawResponse(null);
    try {
      const buf = await new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(r.result);
        r.onerror = reject;
        r.readAsDataURL(file);
      });
      const b64 = typeof buf === 'string' && buf.includes(',') ? buf.split(',')[1] : buf;
      const isPdf = file.type?.includes('pdf') || /\.pdf$/i.test(file.name);
      const res = await menuFeaturesAPI.aiPreviewMenu({ fileData: b64, fileType: isPdf ? 'pdf' : 'image' });
      const d = res.data || {};
      if (!d.count) {
        toast.error(d.message || 'No items detected');
        setRawResponse(d.rawResponse || null);
        setLoading(false);
        return;
      }
      setItems(d.items || []);
      setKnownCats(d.knownCategories || []);
      setKnownMods(d.knownModifiers || []);
      setStage('review');
    } catch (err) {
      toast.error(err?.response?.status === 413
        ? 'Menu file is too large. Choose a file under 3 MB.'
        : err?.response?.data?.detail || err?.message || 'Preview failed');
    } finally {
      setLoading(false);
      input.value = '';
    }
  };

  const handleTextSubmit = async () => {
    const text = menuText.trim();
    if (!text) return;
    setLoading(true);
    setRawResponse(null);
    try {
      const res = await menuFeaturesAPI.aiPreviewMenu({ fileData: text, fileType: 'text' });
      const d = res.data || {};
      if (!d.count) {
        toast.error(d.message || 'No items detected');
        setRawResponse(d.rawResponse || null);
        setLoading(false);
        return;
      }
      setItems(d.items || []);
      setKnownCats(d.knownCategories || []);
      setKnownMods(d.knownModifiers || []);
      setStage('review');
    } catch (err) {
      toast.error(err?.response?.status === 413
        ? 'Menu text is too long. Paste a shorter section.'
        : err?.response?.data?.detail || err?.message || 'Preview failed');
    } finally {
      setLoading(false);
    }
  };

  const updateItem = (tempId, patch) => {
    setItems(prev => prev.map(it => it.tempId === tempId ? { ...it, ...patch } : it));
  };

  const toggleMod = (tempId, modId) => {
    setItems(prev => prev.map(it => {
      if (it.tempId !== tempId) return it;
      const cur = it.suggestedModifierIds || [];
      return { ...it, suggestedModifierIds: cur.includes(modId) ? cur.filter(x => x !== modId) : [...cur, modId] };
    }));
  };

  const selectedCount = useMemo(() => items.filter(i => i.include).length, [items]);
  const duplicateCount = useMemo(() => items.filter(i => i.isDuplicate).length, [items]);
  const totalRevenue = useMemo(
    () => items.filter(i => i.include).reduce((s, i) => s + (Number(i.price) || 0), 0),
    [items]
  );

  const bulkSet = (include) => setItems(prev => prev.map(it => ({ ...it, include })));

  const handleCommit = async () => {
    const payload = items
      .filter(i => i.include && (i.name || '').trim())
      .map(i => ({
        name: i.name,
        category: i.category,
        categoryId: i.categoryId || null,
        price: Number(i.price) || 0,
        cost: Number(i.cost) || 0,
        description: i.description || '',
        modifierIds: i.suggestedModifierIds || [],
        skipIfDuplicate: true,
      }));
    if (payload.length === 0) {
      toast.error('Select at least one item to import');
      return;
    }
    setCommitting(true);
    try {
      const res = await menuFeaturesAPI.aiCommitMenu({ items: payload });
      const d = res.data || {};
      toast.success(d.message || `Imported ${d.created} · Skipped ${d.skipped}`);
      onCommitted?.(d);
      setStage('done');
    } catch (err) {
      toast.error(err?.response?.data?.detail || err?.message || 'Commit failed');
    } finally {
      setCommitting(false);
    }
  };

  const modsForCategory = (catName) => knownMods.filter(m => (m.assignedCategories || []).includes(catName));

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-hidden flex flex-col" data-testid="ai-import-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles size={18} className="text-amber-500" /> AI Menu Import
            {stage === 'review' && <Badge className="ml-2 bg-amber-100 text-amber-700">Review</Badge>}
            {stage === 'done' && <Badge className="ml-2 bg-emerald-100 text-emerald-700">Done</Badge>}
          </DialogTitle>
          <DialogDescription>
            {stage === 'upload' && 'Upload a menu image or PDF, or paste menu text — NUA will detect items, guess categories, and suggest modifiers. You review before anything is saved.'}
            {stage === 'review' && `Detected ${items.length} item${items.length === 1 ? '' : 's'}. Edit anything you like, tick modifiers, then commit only what you want.`}
            {stage === 'done' && 'Import complete. Items are now available in Products and on the POS.'}
          </DialogDescription>
        </DialogHeader>

        {stage === 'upload' && (
          <div className="space-y-4 py-2">
            <div className="border-2 border-dashed rounded-lg p-8 text-center hover:border-amber-400 transition-colors">
              <Upload size={36} className="mx-auto mb-2 text-gray-400" />
              <p className="text-sm text-gray-600 mb-3">Drop your menu file here or click to browse</p>
              <input
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.webp,.gif,application/pdf,image/jpeg,image/png,image/webp,image/gif"
                onChange={handleFileUpload}
                disabled={loading}
                className="w-full text-sm"
                data-testid="menu-file-input"
              />
              <p className="text-[11px] text-gray-400 mt-3">JPG, PNG, WebP, GIF or PDF (including scans) · Maximum 3 MB</p>
            </div>
            <div className="flex items-center gap-2 text-[11px] text-gray-400">
              <div className="flex-1 border-t" /> or <div className="flex-1 border-t" />
            </div>
            <div className="space-y-2">
              <textarea
                value={menuText}
                onChange={(e) => setMenuText(e.target.value)}
                disabled={loading}
                placeholder="Paste your menu text here…"
                rows={5}
                className="w-full text-sm border rounded-lg p-2 resize-none"
                data-testid="menu-text-input"
              />
              <Button size="sm" onClick={handleTextSubmit} disabled={loading || !menuText.trim()} data-testid="menu-text-submit">
                Extract from pasted text
              </Button>
            </div>
            {loading && (
              <div className="flex items-center justify-center gap-2 text-sm text-gray-500" data-testid="preview-loading">
                <Loader2 size={16} className="animate-spin" /> NUA is reading your menu…
              </div>
            )}
            {rawResponse && (
              <details className="text-xs text-gray-400 border rounded p-2">
                <summary className="cursor-pointer">Raw LLM response (debug)</summary>
                <pre className="whitespace-pre-wrap max-h-40 overflow-auto">{rawResponse}</pre>
              </details>
            )}
          </div>
        )}

        {stage === 'review' && (
          <div className="flex-1 overflow-hidden flex flex-col" data-testid="review-stage">
            {/* Stat strip */}
            <div className="grid grid-cols-4 gap-2 mb-3 text-sm">
              <div className="border rounded-lg p-3">
                <p className="text-[10px] uppercase text-gray-500 font-bold">Detected</p>
                <p className="text-2xl font-bold" data-testid="stat-detected">{items.length}</p>
              </div>
              <div className="border rounded-lg p-3">
                <p className="text-[10px] uppercase text-gray-500 font-bold">Selected</p>
                <p className="text-2xl font-bold text-emerald-600" data-testid="stat-selected">{selectedCount}</p>
              </div>
              <div className="border rounded-lg p-3">
                <p className="text-[10px] uppercase text-gray-500 font-bold">Duplicates</p>
                <p className="text-2xl font-bold text-amber-600" data-testid="stat-duplicates">{duplicateCount}</p>
              </div>
              <div className="border rounded-lg p-3">
                <p className="text-[10px] uppercase text-gray-500 font-bold">Menu Value</p>
                <p className="text-2xl font-bold" data-testid="stat-revenue">${totalRevenue.toFixed(2)}</p>
              </div>
            </div>

            {/* Bulk actions */}
            <div className="flex gap-2 mb-2 items-center flex-wrap">
              <Button variant="outline" size="sm" onClick={() => bulkSet(true)} data-testid="bulk-select-all">Select all</Button>
              <Button variant="outline" size="sm" onClick={() => bulkSet(false)} data-testid="bulk-deselect-all">Deselect all</Button>
              <span className="text-xs text-gray-500 ml-2">
                Categories in <span className="text-emerald-600 font-medium">green</span> match an existing category; <span className="text-amber-600 font-medium">amber</span> means a new category will be created.
              </span>
            </div>

            {/* Item table */}
            <div className="flex-1 overflow-auto border rounded-lg" data-testid="review-table">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-[11px] uppercase text-gray-500 sticky top-0">
                  <tr>
                    <th className="p-2 w-8"></th>
                    <th className="p-2 text-left">Name</th>
                    <th className="p-2 text-left">Category</th>
                    <th className="p-2 text-right">Price</th>
                    <th className="p-2 text-right">Cost</th>
                    <th className="p-2 text-right">Margin</th>
                    <th className="p-2 text-left">Modifiers</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it, idx) => {
                    const margin = it.price > 0 ? ((it.price - it.cost) / it.price) * 100 : 0;
                    const catMods = modsForCategory(it.category);
                    return (
                      <tr key={it.tempId} className={`border-t ${!it.include ? 'opacity-40' : ''} ${it.isDuplicate ? 'bg-amber-50/40' : ''}`} data-testid={`review-row-${idx}`}>
                        <td className="p-2 align-top">
                          <input
                            type="checkbox"
                            checked={!!it.include}
                            onChange={e => updateItem(it.tempId, { include: e.target.checked })}
                            data-testid={`row-include-${idx}`}
                          />
                        </td>
                        <td className="p-2 align-top">
                          <Input
                            value={it.name}
                            onChange={e => updateItem(it.tempId, { name: e.target.value })}
                            className="h-8"
                            data-testid={`row-name-${idx}`}
                          />
                          {it.isDuplicate && (
                            <div className="flex items-center gap-1 text-[10px] text-amber-600 mt-1">
                              <AlertTriangle size={11} /> already exists — will be skipped
                            </div>
                          )}
                        </td>
                        <td className="p-2 align-top">
                          <select
                            value={it.categoryId || `__new::${it.category}`}
                            onChange={e => {
                              const val = e.target.value;
                              if (val.startsWith('__new::')) {
                                updateItem(it.tempId, { categoryId: null, category: it.proposedCategory || it.category, categoryMatched: false });
                              } else {
                                const c = knownCats.find(x => x.id === val);
                                if (c) {
                                  updateItem(it.tempId, {
                                    categoryId: c.id,
                                    category: c.name,
                                    categoryMatched: true,
                                    suggestedModifierIds: modsForCategory(c.name).map(m => m.id),
                                  });
                                }
                              }
                            }}
                            className={`h-8 border rounded px-1 text-xs w-full ${it.categoryMatched ? 'border-emerald-300 bg-emerald-50/50' : 'border-amber-300 bg-amber-50/50'}`}
                            data-testid={`row-cat-${idx}`}
                          >
                            {knownCats.map(c => (
                              <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                            {it.proposedCategory && !it.categoryMatched && (
                              <option value={`__new::${it.proposedCategory}`}>➕ New: {it.proposedCategory}</option>
                            )}
                          </select>
                          {!it.categoryMatched && it.proposedCategory && (
                            <div className="text-[10px] text-amber-600 mt-1">AI suggested &ldquo;{it.proposedCategory}&rdquo; — will be created</div>
                          )}
                        </td>
                        <td className="p-2 align-top">
                          <Input
                            type="number"
                            step="0.01"
                            value={it.price}
                            onChange={e => updateItem(it.tempId, { price: e.target.value })}
                            className="h-8 text-right w-24"
                            data-testid={`row-price-${idx}`}
                          />
                        </td>
                        <td className="p-2 align-top">
                          <Input
                            type="number"
                            step="0.01"
                            value={it.cost}
                            onChange={e => updateItem(it.tempId, { cost: e.target.value })}
                            className="h-8 text-right w-24"
                            data-testid={`row-cost-${idx}`}
                          />
                        </td>
                        <td className="p-2 align-top text-right font-medium tabular-nums">
                          <span className={margin >= 60 ? 'text-emerald-600' : margin >= 40 ? 'text-amber-600' : 'text-red-600'}>
                            {margin.toFixed(1)}%
                          </span>
                        </td>
                        <td className="p-2 align-top">
                          {catMods.length === 0 ? (
                            <span className="text-[10px] text-gray-400">no modifiers for this category</span>
                          ) : (
                            <div className="flex flex-wrap gap-1">
                              {catMods.map(m => {
                                const on = (it.suggestedModifierIds || []).includes(m.id);
                                return (
                                  <button
                                    key={m.id}
                                    onClick={() => toggleMod(it.tempId, m.id)}
                                    className={`text-[10px] px-1.5 py-0.5 rounded-full border transition ${on ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-500 border-gray-300 hover:border-indigo-400'}`}
                                    data-testid={`row-mod-${idx}-${m.id}`}
                                  >
                                    {m.name}
                                  </button>
                                );
                              })}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex justify-between items-center mt-3">
              <Button variant="outline" onClick={() => reset()} disabled={committing} data-testid="back-to-upload">
                <ChevronLeft size={14} className="mr-1" /> Back
              </Button>
              <Button
                onClick={handleCommit}
                disabled={committing || selectedCount === 0}
                className="bg-emerald-600 hover:bg-emerald-700 text-white"
                data-testid="commit-btn"
              >
                {committing ? <><Loader2 size={14} className="mr-1 animate-spin" /> Importing…</> : <><CheckCircle2 size={14} className="mr-1" /> Import {selectedCount} item{selectedCount === 1 ? '' : 's'}</>}
              </Button>
            </div>
          </div>
        )}

        {stage === 'done' && (
          <div className="py-6 text-center space-y-4" data-testid="done-stage">
            <div className="w-16 h-16 mx-auto rounded-full bg-emerald-100 flex items-center justify-center">
              <CheckCircle2 size={32} className="text-emerald-600" />
            </div>
            <p className="text-gray-700">Menu import complete. Items are live on the POS.</p>
            <div className="flex gap-2 justify-center">
              <Button variant="outline" onClick={() => reset()} data-testid="import-another">Import another</Button>
              <Button onClick={() => handleClose(false)} data-testid="close-dialog">Close</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
