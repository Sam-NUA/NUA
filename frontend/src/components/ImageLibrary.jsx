import React, { useEffect, useRef, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Card, CardContent } from './ui/card';
import { Upload, Search, Trash2, Image as ImageIcon, X, Check } from 'lucide-react';
import { productImagesAPI } from '../services/api';
import { toast } from 'sonner';
import { DialogService } from '../platform';

/**
 * Image Library: owner uploads images once (stored as base64 in Mongo) and
 * picks them when editing products. Supports search, tags, upload (with
 * client-side downscale), and delete.
 *
 * Props:
 *  - open: boolean
 *  - onClose: () => void
 *  - onPick: (dataUrl: string) => void   — invoked when user picks an image
 *  - themeColor?: string (defaults to NUA orange)
 */
export default function ImageLibrary({ open, onClose, onPick, themeColor = '#f58c14' }) {
  const [images, setImages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);
  const [tags, setTags] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await productImagesAPI.list(search ? { search } : {});
      setImages(res.data || []);
    } catch {
      toast.error('Could not load image library');
    } finally { setLoading(false); }
  };

  useEffect(() => { if (open) load(); }, [open]);

  // Down-scale an image file to max 800px wide @ 0.85 quality before upload
  const downscale = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        const maxW = 800;
        const scale = Math.min(1, maxW / img.width);
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        const out = canvas.toDataURL('image/jpeg', 0.85);
        resolve({ dataUrl: out, contentType: 'image/jpeg' });
      };
      img.onerror = reject;
      img.src = e.target.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      toast.error('Pick an image file');
      return;
    }
    setUploading(true);
    try {
      const { dataUrl, contentType } = await downscale(file);
      const name = file.name.replace(/\.[^/.]+$/, '') || 'untitled';
      const tagList = tags.split(',').map(t => t.trim()).filter(Boolean);
      await productImagesAPI.upload({ name, contentType, dataUrl, tags: tagList });
      toast.success('Uploaded');
      setTags('');
      setUploadOpen(false);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const remove = async (id) => {
    if (!await DialogService.confirm('Delete this image from library? (Products using it keep their copy.)')) return;
    try {
      await productImagesAPI.delete(id);
      toast.success('Deleted');
      load();
    } catch { toast.error('Failed'); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col" data-testid="image-library">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><ImageIcon size={18} style={{ color: themeColor }} /> Image Library</DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 pb-2 border-b" data-no-swipe>
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
            <Input
              placeholder="Search by name…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') load(); }}
              className="pl-9 h-9"
              data-testid="image-search"
            />
          </div>
          <Button variant="outline" onClick={load} className="h-9" data-testid="image-refresh">Refresh</Button>
          <Button onClick={() => setUploadOpen(true)} style={{ background: themeColor }} className="h-9 text-white" data-testid="image-upload-open">
            <Upload size={14} className="mr-1.5" /> Upload
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto -mx-2 px-2 py-2">
          {loading ? (
            <p className="text-center text-gray-400 py-8 text-sm">Loading…</p>
          ) : images.length === 0 ? (
            <p className="text-center text-gray-400 py-12 text-sm">No images in library — tap Upload</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
              {images.map(img => (
                <div key={img.id} className="relative group rounded-lg overflow-hidden border bg-gray-50 hover:shadow-md transition-all" data-testid={`image-${img.id}`}>
                  <img src={img.dataUrl} alt={img.name} className="w-full h-32 object-cover" loading="lazy" />
                  <div className="p-2">
                    <p className="text-xs font-medium truncate" title={img.name}>{img.name}</p>
                    {img.tags?.length > 0 && (
                      <p className="text-[10px] text-gray-400 truncate">{img.tags.join(', ')}</p>
                    )}
                  </div>
                  <div className="absolute inset-x-0 top-0 flex items-start justify-end p-1.5 opacity-0 group-hover:opacity-100 transition-opacity gap-1">
                    <button
                      onClick={() => { onPick(img.dataUrl); onClose(); }}
                      className="bg-white/90 hover:bg-white text-emerald-700 px-2 py-1 rounded text-[10px] font-bold shadow flex items-center gap-1"
                      data-testid={`pick-image-${img.id}`}
                    >
                      <Check size={11} /> Use
                    </button>
                    <button
                      onClick={() => remove(img.id)}
                      className="bg-white/90 hover:bg-red-50 text-red-600 px-2 py-1 rounded text-[10px] font-bold shadow"
                      data-testid={`del-image-${img.id}`}
                      title="Delete"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {uploadOpen && (
          <div className="border rounded-lg p-3 mt-2 bg-amber-50/50" data-testid="image-upload-panel">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-bold">Upload a new image</p>
              <button onClick={() => setUploadOpen(false)} className="text-gray-400 hover:text-red-600"><X size={14} /></button>
            </div>
            <Input
              placeholder="Tags (comma separated, e.g. coffee, drink)"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              className="mb-2 h-9"
              data-testid="image-tags-input"
            />
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={handleFileChange}
              disabled={uploading}
              className="text-sm"
              data-testid="image-file-input"
            />
            {uploading && <p className="text-xs text-amber-700 mt-1">Compressing & uploading…</p>}
            <p className="text-[10px] text-gray-500 mt-1">Auto-compressed to ≤800px wide / 85% JPEG (~150-400 KB).</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
