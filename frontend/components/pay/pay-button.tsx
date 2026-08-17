'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';

export function PayButton({ code, label }: { code: string; label: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch('/api/stripe/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? `Checkout failed (${res.status}).`);
      window.location.href = body.url;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="mt-6">
      <Button onClick={start} disabled={busy} className="w-full">
        {busy ? 'Opening checkout…' : label}
      </Button>
      {error && <p className="text-destructive mt-2 text-sm">{error}</p>}
      <p className="text-muted-foreground mt-3 text-xs">
        Test mode. Use card 4242 4242 4242 4242, any future expiry, any CVC.
      </p>
    </div>
  );
}
