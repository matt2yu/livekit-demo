import { PayButton } from '@/components/pay/pay-button';
import {
  type Order,
  amountDue,
  describeItem,
  formatMoney,
  getSupabase,
  isCatering,
} from '@/lib/supabase';

// Never prerendered: the row changes under it, and a cached "unpaid" page is
// worse than no page at all.
export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Hire Slice — payment',
};

function Shell({ children }: React.PropsWithChildren) {
  return (
    <main className="mx-auto max-w-md px-6 pt-24 pb-16">
      <div className="bg-card text-card-foreground rounded-lg border p-6 shadow-sm">{children}</div>
    </main>
  );
}

export default async function PayPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;

  const { data, error } = await getSupabase()
    .from('orders')
    .select('*')
    .eq('code', code.toUpperCase())
    .maybeSingle();

  if (error) {
    return (
      <Shell>
        <h1 className="text-lg font-bold">Something went wrong</h1>
        <p className="text-muted-foreground mt-2 text-sm">{error.message}</p>
      </Shell>
    );
  }

  if (!data) {
    return (
      <Shell>
        <h1 className="text-lg font-bold">No order {code.toUpperCase()}</h1>
        <p className="text-muted-foreground mt-2 text-sm">
          Check the code we read back to you on the call.
        </p>
      </Shell>
    );
  }

  const order = data as Order;

  if (!isCatering(order)) {
    return (
      <Shell>
        <h1 className="text-lg font-bold">Nothing to pay</h1>
        <p className="text-muted-foreground mt-2 text-sm">
          Order {order.code} is paid at the counter or on delivery.
        </p>
      </Shell>
    );
  }

  return (
    <Shell>
      <h1 className="text-lg font-bold">
        {order.deposit_paid ? 'Paid — order' : 'Catering order'}{' '}
        <span className="font-mono tracking-widest">{order.code}</span>
      </h1>
      <p className="text-muted-foreground mt-1 text-sm">
        {order.customer_name} — for {order.scheduled_for}
      </p>

      <ul className="mt-4 space-y-1 border-t pt-4 text-sm">
        {order.items.map((item, i) => (
          <li key={i} className="flex justify-between gap-4">
            <span>{describeItem(item)}</span>
            <span className="text-muted-foreground shrink-0 font-mono">
              {formatMoney(item.unit_price * item.qty)}
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-3 flex justify-between border-t pt-3 text-sm font-medium">
        <span>Due now, in full</span>
        <span className="font-mono">{formatMoney(amountDue(order))}</span>
      </div>

      {order.deposit_paid ? (
        <p className="mt-6 text-sm font-medium">Paid. The kitchen has it — nothing else to do.</p>
      ) : (
        <PayButton code={order.code} label={`Pay ${formatMoney(amountDue(order))}`} />
      )}
    </Shell>
  );
}
