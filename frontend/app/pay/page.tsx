'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';

/**
 * Code entry, so the agent can say a URL a caller can actually hold in their head.
 *
 * "hire-slice.app/pay, then your code" survives being heard once over a phone.
 * "hire-slice.app/pay/9QP4" does not — the code is the part most likely to be
 * misheard, and it is the part already read back twice on the call.
 */
export default function PayIndexPage() {
  const router = useRouter();
  const [code, setCode] = useState('');

  const clean = code
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '')
    .slice(0, 4);

  return (
    <main className="mx-auto max-w-md px-6 pt-24 pb-16">
      <div className="bg-card text-card-foreground rounded-lg border p-6 shadow-sm">
        <h1 className="text-lg font-bold">Pay for a catering order</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Enter the four-character code we read back to you on the call.
        </p>

        <form
          className="mt-6"
          onSubmit={(e) => {
            e.preventDefault();
            if (clean.length === 4) router.push(`/pay/${clean}`);
          }}
        >
          <input
            autoFocus
            value={clean}
            onChange={(e) => setCode(e.target.value)}
            placeholder="9QP4"
            aria-label="Order code"
            className="border-input bg-background w-full rounded-md border px-4 py-3 text-center font-mono text-2xl tracking-[0.4em] uppercase"
          />
          <Button type="submit" disabled={clean.length !== 4} className="mt-4 w-full">
            Find my order
          </Button>
        </form>
      </div>
    </main>
  );
}
