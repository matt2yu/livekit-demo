import { createClient } from '@supabase/supabase-js';

/**
 * Read-only client for the staff dashboard.
 *
 * Uses the publishable key, which is safe in the browser: RLS restricts anon to
 * SELECT on `orders`. Orders are written by the agent with the secret key, which
 * never reaches this bundle.
 */
export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
  { auth: { persistSession: false } }
);

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
