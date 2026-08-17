'use client';

import { useEffect, useState } from 'react';
import { OrderCard } from '@/components/admin/order-card';
import { type Order, getSupabase, isMakeable } from '@/lib/supabase';

type Status = 'loading' | 'live' | 'error';

export function OrderFeed() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    let supabase;
    try {
      supabase = getSupabase();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus('error');
      return;
    }

    supabase
      .from('orders')
      .select('*')
      .order('placed_at', { ascending: false })
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          setError(error.message);
          setStatus('error');
          return;
        }
        setOrders((data ?? []) as Order[]);
        setStatus('live');
      });

    // An order lands while the caller is still on the line, and a deposit clears
    // minutes later — so INSERT alone is not enough. UPDATE is what flips a
    // catering ticket from blocked to makeable without a refresh.
    const channel = supabase
      .channel('orders-feed')
      .on<Order>(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'orders' },
        ({ new: row }) => {
          setOrders((prev) => (prev.some((o) => o.id === row.id) ? prev : [row, ...prev]));
        }
      )
      .on<Order>(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'orders' },
        ({ new: row }) => {
          setOrders((prev) => prev.map((o) => (o.id === row.id ? { ...o, ...row } : o)));
        }
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, []);

  if (status === 'error') {
    return (
      <p className="text-destructive rounded-lg border border-dashed p-6 text-sm">
        Could not load orders. {error}
      </p>
    );
  }

  if (status === 'loading') {
    return <p className="text-muted-foreground p-6 text-sm">Loading orders…</p>;
  }

  if (orders.length === 0) {
    return (
      <p className="text-muted-foreground rounded-lg border border-dashed p-6 text-sm">
        No orders yet. This list updates itself — leave it open.
      </p>
    );
  }

  const making = orders.filter(isMakeable);
  const blocked = orders.filter((o) => !isMakeable(o));

  return (
    <div className="space-y-8">
      <Section title="Make queue" count={making.length} orders={making} />
      {blocked.length > 0 && (
        <Section title="Awaiting payment" count={blocked.length} orders={blocked} />
      )}
    </div>
  );
}

function Section({ title, count, orders }: { title: string; count: number; orders: Order[] }) {
  return (
    <section>
      <h2 className="text-muted-foreground mb-3 font-mono text-xs font-bold tracking-wider uppercase">
        {title} ({count})
      </h2>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {orders.map((order) => (
          <OrderCard key={order.id} order={order} />
        ))}
      </div>
    </section>
  );
}
