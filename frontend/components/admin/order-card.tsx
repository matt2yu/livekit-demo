import { cn } from '@/lib/shadcn/utils';
import {
  type Order,
  depositDue,
  describeItem,
  formatMoney,
  formatPhone,
  formatTime,
  isCatering,
  isMakeable,
} from '@/lib/supabase';

function Badge({ children, className }: React.PropsWithChildren<{ className?: string }>) {
  return (
    <span
      className={cn(
        'rounded-full border px-2 py-0.5 font-mono text-[10px] font-bold tracking-wider uppercase',
        className
      )}
    >
      {children}
    </span>
  );
}

export function OrderCard({ order }: { order: Order }) {
  const catering = isCatering(order);
  const blocked = !isMakeable(order);

  return (
    <article
      className={cn(
        'bg-card text-card-foreground rounded-lg border p-4 shadow-sm',
        blocked && 'border-dashed opacity-70'
      )}
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xl font-bold tracking-widest">{order.code}</span>
        <span className="text-muted-foreground text-sm">{formatTime(order.placed_at)}</span>

        <span className="grow" />

        <Badge className="border-border text-muted-foreground">{order.channel}</Badge>
        <Badge
          className={
            order.fulfillment === 'delivery'
              ? 'border-primary text-primary'
              : 'border-border text-muted-foreground'
          }
        >
          {order.fulfillment}
        </Badge>
        {catering && <Badge className="border-border text-muted-foreground">catering</Badge>}
      </header>

      {blocked && (
        <p className="text-muted-foreground mt-3 text-sm font-medium">
          Awaiting deposit — {formatMoney(depositDue(order))} of {formatMoney(order.total)}. Do not
          start.
        </p>
      )}

      <div className="mt-3 text-sm">
        <p className="font-medium">
          {order.customer_name}{' '}
          <span className="text-muted-foreground font-normal">
            {formatPhone(order.phone_number)}
          </span>
        </p>
        {order.fulfillment === 'delivery' && order.address && (
          <p className="text-muted-foreground">{order.address}</p>
        )}
        {/* Carrier-supplied, so it is the only number the caller could not choose.
            Shown only when it disagrees with the one they spoke. */}
        {order.caller_id &&
          order.caller_id.replace(/\D/g, '') !== order.phone_number.replace(/\D/g, '') && (
            <p className="text-muted-foreground text-xs">
              called from {formatPhone(order.caller_id)}
            </p>
          )}
      </div>

      {catering && order.scheduled_for && (
        <p className="mt-3 text-sm">
          <span className="text-muted-foreground">for </span>
          <span className="font-medium">{order.scheduled_for}</span>
        </p>
      )}

      <ul className="mt-3 space-y-1 text-sm">
        {order.items.map((item, i) => (
          <li key={i} className="flex justify-between gap-4">
            <span>{describeItem(item)}</span>
            <span className="text-muted-foreground shrink-0 font-mono">
              {formatMoney(item.unit_price * item.qty)}
            </span>
          </li>
        ))}
      </ul>

      <footer className="mt-3 flex justify-between border-t pt-2 text-sm font-medium">
        <span>
          Total
          {order.delivery_fee > 0 && (
            <span className="text-muted-foreground font-normal">
              {' '}
              incl. {formatMoney(order.delivery_fee)} delivery
            </span>
          )}
        </span>
        <span className="font-mono">{formatMoney(order.total)}</span>
      </footer>
    </article>
  );
}
