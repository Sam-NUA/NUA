import React, { useState, useEffect } from 'react';
import { Link2, Plus, Trash2, Copy, ExternalLink, QrCode, X } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { itemsSystemAPI, productsAPI } from '../services/api';
import { toast } from 'sonner';
import { FileService } from '../platform';

export default function PaymentLinks() {
  const { theme } = useTheme();
  const [links, setLinks] = useState([]);
  const [products, setProducts] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState('');
  const [customPrice, setCustomPrice] = useState('');
  const [qrLink, setQrLink] = useState(null);

  useEffect(() => {
    itemsSystemAPI.getPaymentLinks().then(r => setLinks(r.data)).catch(() => {});
    productsAPI.getAll().then(r => setProducts(r.data)).catch(() => {});
  }, []);

  const createLink = async () => {
    const product = products.find(p => p.id === selectedProduct);
    if (!product) { toast.error('Select a product'); return; }
    try {
      const res = await itemsSystemAPI.createPaymentLink({ productId: product.id, productName: product.name, price: parseFloat(customPrice) || product.price });
      setLinks([res.data, ...links]);
      toast.success('Payment link created');
      setSelectedProduct(''); setCustomPrice('');
    } catch { toast.error('Failed'); }
  };

  const copyLink = (url) => { navigator.clipboard.writeText(url); toast.success('Link copied to clipboard'); };

  const downloadQR = async () => {
    const svg = document.getElementById('qr-code-svg');
    if (!svg) return;
    const svgData = new XMLSerializer().serializeToString(svg);
    const blob = new Blob([svgData], { type: 'image/svg+xml' });
    await FileService.downloadFile(blob, `${qrLink?.productName || 'payment-link'}-qr.svg`);
    toast.success('QR code downloaded');
  };

  return (
    <div className="space-y-6" data-testid="payment-links-page">
      <div><h1 className="text-2xl font-bold" style={{ color: theme.text }}>Payment Links</h1><p className="text-sm text-gray-500">Sell items via social media bios, table tents, shop windows — print the QR for instant tap-to-pay</p></div>

      <Card><CardContent className="p-4">
        <p className="text-sm font-medium mb-3">Create Payment Link</p>
        <div className="flex gap-2">
          <select className="flex-1 p-2 border rounded-md text-sm" value={selectedProduct} onChange={e => setSelectedProduct(e.target.value)} data-testid="link-product-select">
            <option value="">Select item...</option>
            {products.map(p => <option key={p.id} value={p.id}>{p.name} — ${p.price}</option>)}
          </select>
          <Input type="number" step="0.01" placeholder="Custom price (optional)" className="w-40" value={customPrice} onChange={e => setCustomPrice(e.target.value)} data-testid="link-price" />
          <Button style={{ backgroundColor: theme.primary }} onClick={createLink} data-testid="create-link-btn"><Plus size={16} className="mr-1" /> Generate Link</Button>
        </div>
      </CardContent></Card>

      <div className="space-y-2">
        {links.map(link => (
          <Card key={link.id} data-testid={`link-${link.id}`}>
            <CardContent className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Link2 size={18} style={{ color: theme.primary }} />
                <div>
                  <p className="font-medium text-sm">{link.productName}</p>
                  <p className="text-xs text-gray-500 font-mono">{link.url}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge style={{ backgroundColor: `${theme.primary}15`, color: theme.primary }}>${link.price}</Badge>
                <Button variant="outline" size="sm" onClick={() => setQrLink(link)} data-testid={`qr-${link.id}`}><QrCode size={13} /></Button>
                <Button variant="outline" size="sm" onClick={() => copyLink(link.url)} data-testid={`copy-${link.id}`}><Copy size={13} /></Button>
                <Button variant="outline" size="sm" className="text-red-500" onClick={async () => { await itemsSystemAPI.deletePaymentLink(link.id); setLinks(links.filter(l => l.id !== link.id)); }}><Trash2 size={13} /></Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {links.length === 0 && <Card className="border-dashed"><CardContent className="py-12 text-center text-gray-400"><Link2 size={40} className="mx-auto mb-3 opacity-30" /><p>No payment links yet. Create one above.</p></CardContent></Card>}
      </div>

      {/* QR Code Modal */}
      <Dialog open={!!qrLink} onOpenChange={(open) => { if (!open) setQrLink(null); }}>
        <DialogContent className="max-w-sm" data-testid="qr-modal">
          <DialogHeader><DialogTitle>Scan to Pay</DialogTitle></DialogHeader>
          {qrLink && (
            <div className="flex flex-col items-center py-2 space-y-3">
              <div className="bg-white p-4 rounded-xl border-2" style={{ borderColor: theme.primary }}>
                <QRCodeSVG id="qr-code-svg" value={qrLink.url} size={220} level="M" includeMargin />
              </div>
              <div className="text-center">
                <p className="font-semibold">{qrLink.productName}</p>
                <p className="text-2xl font-bold mt-1" style={{ color: theme.primary }}>${qrLink.price}</p>
                <p className="text-[10px] text-gray-400 font-mono mt-1 break-all">{qrLink.url}</p>
              </div>
              <div className="flex gap-2 w-full">
                <Button className="flex-1" variant="outline" onClick={downloadQR} data-testid="download-qr-btn">Download QR</Button>
                <Button className="flex-1" onClick={() => copyLink(qrLink.url)} style={{ backgroundColor: theme.primary }} data-testid="copy-qr-btn">Copy Link</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
