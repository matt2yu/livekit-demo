import 'server-only';
import Stripe from 'stripe';
import { type SupabaseClient, createClient } from '@supabase/supabase-js';

let stripe: Stripe | null = null;
let admin: SupabaseClient | null = null;

/**
 * Lazy for the same reason as the browser client: `next build` runs in CI with
 * no secrets, and constructing at module scope would fail the build of every
 * route that imports this file.
 *
 * No `apiVersion` is passed — the SDK pins its own (`stripe/cjs/apiVersion.js`,
 * `2026-07-29.dahlia` on 22.5.0) and its types are generated against exactly
 * that. Naming a different one here would let the types drift from the wire.
 */
export function getStripe(): Stripe {
  if (stripe) return stripe;

  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) {
    throw new Error('STRIPE_SECRET_KEY is not set in frontend/.env.local.');
  }

  stripe = new Stripe(key);
  return stripe;
}

/**
 * Service-role Supabase client. Bypasses RLS, so it never reaches the browser —
 * `server-only` above turns a stray client import into a build error rather
 * than a leaked key.
 *
 * This is the only thing in the app that can write `deposit_paid`, and only the
 * signature-verified webhook may call it.
 */
export function getSupabaseAdmin(): SupabaseClient {
  if (admin) return admin;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    throw new Error(
      'Supabase service role is not configured. Set NEXT_PUBLIC_SUPABASE_URL and ' +
        'SUPABASE_SERVICE_ROLE_KEY in frontend/.env.local.'
    );
  }

  admin = createClient(url, key, { auth: { persistSession: false } });
  return admin;
}
