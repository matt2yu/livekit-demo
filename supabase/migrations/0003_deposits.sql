-- Catering deposits, paid through Stripe.
--
-- 0002 added deposit_paid but nothing could ever set it. This adds the audit
-- trail linking a row to the payment that flipped it, and makes the dashboard's
-- realtime UPDATE useful.
--
-- Apply in the Supabase SQL editor.

alter table orders add column if not exists stripe_session_id text;

comment on column orders.stripe_session_id is
    'Stripe Checkout Session that paid the deposit. The audit trail behind deposit_paid.';

-- The dashboard subscribes to UPDATE so a cleared deposit flips a blocked
-- catering ticket while the kitchen is looking at it. Under the default replica
-- identity an UPDATE payload carries only the primary key for the old row, and
-- the filter and diff both want the whole row.
alter table orders replica identity full;

-- Deliberately no policy granting anon UPDATE. deposit_paid is writable only by
-- the signature-verified webhook, which holds the service role key and bypasses
-- RLS. If the browser could set it, a prankster would set it with curl.
