import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Eye, RotateCw, Users, Zap, AlertCircle, CheckCircle2, Clock, DollarSign } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { toast } from 'sonner';
import api from '../services/api';

export function SplitBillStaff() {
  const [splits, setSplits] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedSplitId, setSelectedSplitId] = useState(null);
  const [refreshInterval] = useState(3000);
  const [connectedIds, setConnectedIds] = useState({});
  const [processingTabIds, setProcessingTabIds] = useState({});
  const wsRef = useRef({});
  // One idempotency key per tab, generated on first attempt and reused for
  // every retry of that same tab — so a network timeout + resend, or an
  // impatient double-click before the button's disabled state paints,
  // can never record the same cash collection twice.
  const tabIdempotencyKeysRef = useRef({});

  const pollSplits = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/table/active-splits');
      setSplits(res.data.splits || []);
    } catch (e) {
      if (e?.response?.status === 401) {
        toast.error('Session expired, please log in again');
      } else {
        console.error('Failed to fetch splits:', e);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    pollSplits();
    const interval = setInterval(pollSplits, refreshInterval);
    return () => clearInterval(interval);
  }, [pollSplits, refreshInterval]);

  // Open one WebSocket per active split, skipping ones already connected —
  // runs as an effect (not inline during render) so it only fires when the
  // set of active split ids actually changes, not on every render.
  useEffect(() => {
    const ids = splits.map(s => s.id);
    for (const id of ids) {
      if (wsRef.current[id]) continue;
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws/split/${id}`);
      ws.onopen = () => setConnectedIds(prev => ({ ...prev, [id]: true }));
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'split_updated' && data.data) {
            setSplits(prev => prev.map(s => (s.id === id ? { ...s, ...data.data } : s)));
          } else {
            pollSplits();
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };
      ws.onclose = () => {
        setConnectedIds(prev => {
          const next = { ...prev };
          delete next[id];
          return next;
        });
        delete wsRef.current[id];
      };
      wsRef.current[id] = ws;
    }
    // Close sockets for splits that dropped off the active list (settled/gone).
    for (const id of Object.keys(wsRef.current)) {
      if (!ids.includes(id)) {
        wsRef.current[id].close();
        delete wsRef.current[id];
      }
    }
  }, [splits, pollSplits]);

  useEffect(() => () => {
    Object.values(wsRef.current).forEach(ws => ws.close());
  }, []);

  const handleProcessTab = async (splitId, tabId, amount) => {
    if (processingTabIds[tabId]) return;
    if (!tabIdempotencyKeysRef.current[tabId]) {
      tabIdempotencyKeysRef.current[tabId] = crypto.randomUUID();
    }
    const idempotencyKey = tabIdempotencyKeysRef.current[tabId];
    setProcessingTabIds(prev => ({ ...prev, [tabId]: true }));
    try {
      await api.post(`/table/split/${splitId}/staff-process-tab`,
        { tabId, amount, method: 'cash', idempotencyKey });
      toast.success('Tab processed successfully');
      delete tabIdempotencyKeysRef.current[tabId];
      pollSplits();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to process tab');
    } finally {
      setProcessingTabIds(prev => {
        const next = { ...prev };
        delete next[tabId];
        return next;
      });
    }
  };

  const calculateStats = (split) => {
    const lines = split.lines || [];
    const slots = split.equalParts || [];
    const all = [...lines, ...slots];
    return {
      open: all.filter((l) => l.status === 'open').length,
      claimed: all.filter((l) => l.status === 'claimed').length,
      paid: all.filter((l) => l.status === 'paid').length,
      total: all.length,
    };
  };

  const getCompletionPercentage = (split) => {
    const stats = calculateStats(split);
    return stats.total > 0 ? Math.round((stats.paid / stats.total) * 100) : 0;
  };

  const selectedSplit = splits.find(s => s.id === selectedSplitId) || null;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 p-4 md:p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-gray-800 flex items-center gap-2 mb-2">
            <Zap size={32} className="text-blue-600" />
            Staff Monitor
          </h1>
          <p className="text-gray-600">Real-time bill split tracking across tables</p>
        </div>

        {/* Controls */}
        <div className="flex gap-2 mb-6">
          <Button
            onClick={pollSplits}
            disabled={loading}
            className="gap-2"
            size="sm"
          >
            <RotateCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
          </Button>
          <div className="text-sm text-gray-600 flex items-center gap-2">
            <Clock size={16} />
            Auto-refresh every {refreshInterval / 1000}s
          </div>
        </div>

        {/* Active Splits Grid */}
        {splits.length === 0 ? (
          <Card>
            <CardContent className="pt-6">
              <div className="text-center text-gray-500">
                <Zap size={32} className="mx-auto mb-2 opacity-50" />
                <p>No active bill splits at this time</p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {splits.map((split) => {
              const stats = calculateStats(split);
              const completion = getCompletionPercentage(split);
              const isConnected = !!connectedIds[split.id];

              return (
                <Card
                  key={split.id}
                  className={`cursor-pointer transition-shadow hover:shadow-lg ${
                    selectedSplitId === split.id ? 'ring-2 ring-blue-500' : ''
                  }`}
                  onClick={() => setSelectedSplitId(split.id)}
                >
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between">
                      <div>
                        <CardTitle className="text-lg">Table {split.tableNumber}</CardTitle>
                        <p className="text-xs text-gray-500 mt-1">
                          {split.createdAt ? new Date(split.createdAt).toLocaleTimeString() : ''}
                        </p>
                      </div>
                      <div className="flex gap-1">
                        {isConnected ? (
                          <Badge className="bg-green-100 text-green-800 flex items-center gap-1">
                            <Zap size={12} />
                            Live
                          </Badge>
                        ) : (
                          <Badge className="bg-yellow-100 text-yellow-800">
                            Connecting...
                          </Badge>
                        )}
                      </div>
                    </div>
                  </CardHeader>

                  <CardContent className="space-y-4">
                    {/* Progress */}
                    <div>
                      <div className="flex justify-between text-xs font-medium text-gray-700 mb-1">
                        <span>Progress</span>
                        <span>{completion}%</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-green-500 h-2 rounded-full transition-all duration-300"
                          style={{ width: `${completion}%` }}
                        />
                      </div>
                    </div>

                    {/* Stats */}
                    <div className="grid grid-cols-3 gap-2">
                      <div className="text-center p-2 rounded bg-blue-50 border border-blue-200">
                        <div className="font-bold text-blue-900">{stats.open}</div>
                        <div className="text-xs text-blue-700">Open</div>
                      </div>
                      <div className="text-center p-2 rounded bg-yellow-50 border border-yellow-200">
                        <div className="font-bold text-yellow-900">{stats.claimed}</div>
                        <div className="text-xs text-yellow-700">Claimed</div>
                      </div>
                      <div className="text-center p-2 rounded bg-green-50 border border-green-200">
                        <div className="font-bold text-green-900">{stats.paid}</div>
                        <div className="text-xs text-green-700">Paid</div>
                      </div>
                    </div>

                    {/* Bill Total */}
                    <div className="pt-2 border-t">
                      <div className="flex justify-between items-center">
                        <span className="text-sm font-medium text-gray-700">Bill Total:</span>
                        <span className="text-lg font-bold text-gray-900">
                          ${(split.totalAmount || 0).toFixed(2)}
                        </span>
                      </div>
                    </div>

                    {/* Group Info */}
                    {split.groupId && (
                      <div className="pt-2 border-t flex items-center gap-2 text-xs text-gray-600">
                        <Users size={14} />
                        <span>Group split with {split.participants?.length || 1} guest(s)</span>
                      </div>
                    )}

                    {/* Action */}
                    <Button
                      size="sm"
                      variant="outline"
                      className="w-full"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedSplitId(split.id);
                      }}
                    >
                      <Eye size={14} /> View Details
                    </Button>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}

        {/* Detail Panel */}
        {selectedSplit && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
            <Card className="w-full max-w-2xl max-h-96 overflow-y-auto">
              <CardHeader className="flex flex-row items-center justify-between pb-3">
                <CardTitle>Table {selectedSplit.tableNumber} - Details</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedSplitId(null)}
                >
                  ✕
                </Button>
              </CardHeader>

              <CardContent className="space-y-4">
                {/* Items */}
                <div>
                  <h3 className="font-semibold text-sm mb-2">Items</h3>
                  <div className="space-y-1 text-sm">
                    {(selectedSplit.lines || []).map((line) => (
                      <div
                        key={line.id}
                        className="flex justify-between items-center p-2 bg-gray-50 rounded"
                      >
                        <span className="font-medium">{line.productName}</span>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">${line.unitPrice.toFixed(2)}</span>
                          <Badge
                            className={
                              line.status === 'paid'
                                ? 'bg-green-100 text-green-800'
                                : line.status === 'claimed'
                                ? 'bg-yellow-100 text-yellow-800'
                                : 'bg-blue-100 text-blue-800'
                            }
                          >
                            {line.status}
                          </Badge>
                        </div>
                      </div>
                    ))}
                    {(selectedSplit.equalParts || []).map((slot) => (
                      <div
                        key={slot.index}
                        className="flex justify-between items-center p-2 bg-gray-50 rounded"
                      >
                        <span className="font-medium">Share #{slot.index + 1}</span>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">${slot.amount.toFixed(2)}</span>
                          <Badge
                            className={
                              slot.status === 'paid'
                                ? 'bg-green-100 text-green-800'
                                : slot.status === 'claimed'
                                ? 'bg-yellow-100 text-yellow-800'
                                : 'bg-blue-100 text-blue-800'
                            }
                          >
                            {slot.status}
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Guests/Claims */}
                {selectedSplit.claims?.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-sm mb-2">Guest Claims</h3>
                    <div className="space-y-2">
                      {selectedSplit.claims.map((claim, i) => (
                        <div
                          key={i}
                          className="p-2 bg-gray-50 rounded flex justify-between items-center text-sm"
                        >
                          <div>
                            <div className="font-medium">{claim.phone}</div>
                            <div className="text-xs text-gray-500">
                              {claim.items.length} items
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="font-semibold">${claim.total.toFixed(2)}</span>
                            {claim.paid ? (
                              <CheckCircle2 size={16} className="text-green-600" />
                            ) : (
                              <Clock size={16} className="text-yellow-600" />
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Open Tabs */}
                {selectedSplit.openTabs?.length > 0 && (
                  <div>
                    <h3 className="font-semibold text-sm mb-2 flex items-center gap-2">
                      <AlertCircle size={16} />
                      Open Tabs (Payment Pending)
                    </h3>
                    <div className="space-y-2">
                      {selectedSplit.openTabs.map((tab) => (
                        <div
                          key={tab.id}
                          className="p-2 bg-amber-50 rounded border border-amber-200"
                        >
                          <div className="flex justify-between items-start mb-2">
                            <div>
                              <div className="font-medium text-sm">{tab.guestPhone}</div>
                              <div className="text-xs text-gray-600">
                                {(tab.claimedLines || []).length} items claimed
                              </div>
                            </div>
                            <Badge className="bg-amber-100 text-amber-800">Open Tab</Badge>
                          </div>
                          <div className="flex justify-between items-center text-sm">
                            <div>
                              <span className="text-gray-600">Remaining: </span>
                              <span className="font-bold">${tab.remainingBalance.toFixed(2)}</span>
                            </div>
                            <Button
                              size="sm"
                              disabled={!!processingTabIds[tab.id]}
                              onClick={() => handleProcessTab(selectedSplit.id, tab.id, tab.remainingBalance)}
                              className="gap-1"
                            >
                              <DollarSign size={14} />
                              {processingTabIds[tab.id] ? 'Processing…' : 'Process'}
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Close Button */}
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={() => setSelectedSplitId(null)}
                >
                  Close
                </Button>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}

export default SplitBillStaff;
