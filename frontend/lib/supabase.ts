import { type SupabaseClient, createClient } from '@supabase/supabase-js';

let client: SupabaseClient | null = null;

/**
 * Read-only client for the staff dashboard.
 *
 * Uses the publishable key, which is safe in the browser: RLS restricts anon to
 * SELECT on `orders`. Orders are written by the agent with the secret key, which
 * never reaches this bundle.
 *
 * Lazy, not module scope: `createClient(undefined, ...)` throws, and `next build`
 * runs in CI with no Supabase env vars. Constructing at import time would fail the
 * build of any route that imports this file, where the error is least actionable.
 */
export function getSupabase(): SupabaseClient {
  if (client) return client;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) {
    throw new Error(
      'Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and ' +
        'NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY in frontend/.env.local.'
    );
  }

  client = createClient(url, key, { auth: { persistSession: false } });
  return client;
}

export interface OrderItem {
  category: 'pizza' | 'drink' | 'sauce';
  item: string;
  size: string | null;
  toppings: string[];
  qty: number;
  unit_price: number;
}

export interface Order {
  id: number;
  code: string;
  placed_at: string;
  channel: 'phone' | 'web';
  room: string | null;
  customer_name: string;
  phone_number: string;
  fulfillment: 'pickup' | 'delivery';
  address: string | null;
  items: OrderItem[];
  subtotal: number;
  delivery_fee: number;
  total: number;

  /** The caller's own words — "Saturday lunchtime". Null on a normal order. */
  scheduled_for: string | null;
  deposit_link_sent: boolean;
  deposit_paid: boolean;
  /** Carrier-supplied. Unlike phone_number, the caller cannot choose it. */
  caller_id: string | null;
}

export function isCatering(order: Order): boolean {
  return order.scheduled_for !== null;
}

/**
 * Whether the kitchen may start making this order.
 *
 * Data, not judgement — but only half the rule can be data. A catering order is
 * blocked until its deposit clears, which is a boolean. Whether its time has
 * arrived is not: `scheduled_for` is text on purpose ("Saturday lunchtime"), so
 * the timing stays a human read of the ticket rather than a parse that would
 * invent precision the caller never gave.
 */
export function isMakeable(order: Order): boolean {
  return !isCatering(order) || order.deposit_paid;
}

/**
 * What a catering order must pay before the kitchen starts: all of it.
 *
 * A part-payment leaves the shop carrying the rest of a four-figure order on a
 * promise from someone who rang once. Prepaying in full is also the only thing
 * that makes a prank catering order cost the prankster rather than the kitchen.
 *
 * `deposit_paid` keeps its name — the column means the money cleared, and
 * renaming it would reach into the agent, its tests, and the prompt.
 */
export function amountDue(order: Order): number {
  return order.total;
}

export function formatMoney(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

export function describeItem(item: OrderItem): string {
  const parts: string[] = [];
  if (item.qty > 1) parts.push(`${item.qty}×`);
  if (item.size) parts.push(item.size);
  parts.push(item.item);
  const text = parts.join(' ');
  return item.toppings.length ? `${text} + ${item.toppings.join(', ')}` : text;
}

/** 5551234567 -> (555) 123-4567 */
export function formatPhone(raw: string): string {
  const digits = raw.replace(/\D/g, '').slice(-10);
  if (digits.length !== 10) return raw;
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
}
