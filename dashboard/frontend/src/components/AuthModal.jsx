import React, { useState } from 'react';
import { Key, Shield, Check, AlertCircle, LogOut } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

export function AuthModal({ isOpen, onClose, currentRole, onKeySaved, showToast }) {
  const [apiKey, setApiKey] = useState(localStorage.getItem('ara_api_key') || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSave = async (e) => {
    if (e) e.preventDefault();
    const cleanKey = apiKey.trim();
    if (!cleanKey) {
      localStorage.removeItem('ara_api_key');
      onKeySaved(null);
      onClose();
      if (showToast) showToast('Auth key cleared');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/auth/verify', {
        headers: { Authorization: `Bearer ${cleanKey}` },
      });
      const data = await res.json();
      if (res.ok && data.authenticated) {
        localStorage.setItem('ara_api_key', cleanKey);
        onKeySaved(data.role);
        onClose();
        if (showToast) showToast(`🔑 Authenticated as ${data.role.toUpperCase()}`);
      } else {
        setError(data.error || 'Invalid API Key');
      }
    } catch (err) {
      setError('Connection failed. Could not verify key with hub.');
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    localStorage.removeItem('ara_api_key');
    setApiKey('');
    onKeySaved(null);
    onClose();
    if (showToast) showToast('Logged out / API key removed');
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md bg-slate-900 border-border text-slate-100">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <Shield className="w-5 h-5" />
            </div>
            <div>
              <DialogTitle className="text-base font-semibold">ARA Authentication & RBAC</DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground">
                Manage your credentials for Autonomous Ops & Telemetry
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSave} className="space-y-4 pt-2">
          <div className="p-3 rounded-lg bg-slate-950/60 border border-border/80 flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Current Access Level:</span>
            <span className="font-semibold px-2 py-0.5 rounded-full border text-[11px] uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
              {currentRole || 'Viewer'}
            </span>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-300 flex items-center justify-between">
              <span>API Key</span>
              <span className="text-[10px] text-muted-foreground">Bearer / Header Token</span>
            </label>
            <div className="relative">
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Paste your ARA API key..."
                className="w-full bg-slate-950 border border-border rounded-lg px-3 py-2 text-xs font-mono text-slate-100 placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="p-2.5 rounded-lg bg-slate-950/40 border border-border/60 text-[11px] text-muted-foreground space-y-1">
            <p className="font-medium text-slate-300">💡 Server CLI Commands:</p>
            <code className="block font-mono text-[10px] text-emerald-400">devctl auth status</code>
            <code className="block font-mono text-[10px] text-emerald-400">devctl auth create-key --role admin</code>
          </div>

          <div className="flex items-center justify-between pt-2">
            {localStorage.getItem('ara_api_key') ? (
              <Button type="button" variant="ghost" size="sm" onClick={handleClear} className="text-rose-400 hover:text-rose-300 h-8 gap-1.5 text-xs">
                <LogOut className="w-3.5 h-3.5" />
                Clear Key
              </Button>
            ) : <div />}

            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={onClose} className="h-8 text-xs">
                Cancel
              </Button>
              <Button type="submit" size="sm" disabled={loading} className="bg-emerald-600 hover:bg-emerald-500 h-8 text-xs gap-1.5 font-medium">
                {loading ? 'Verifying...' : 'Save & Authenticate'}
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
