-- Catering orders.
--
-- Past a threshold an order stops being something the kitchen makes while the
-- caller waits, so it carries a time it was booked for and a record that a
-- deposit link went out. Both are required before such an order can be placed.
--
-- Apply in the Supabase SQL editor.

alter table orders add column if not exists scheduled_for text;
alter table orders add column if not exists deposit_link_sent boolean not null default false;

-- Deliberately text, not timestamptz: the caller says "Saturday lunchtime", and
-- parsing that into an instant would invent precision they never gave. The
-- kitchen reads it the way a paper ticket is read.
comment on column orders.scheduled_for is
    'When the caller asked for a catering order, in their own words. Null for normal orders.';

-- Sent is not paid. Confirming payment needs a webhook from the payment
-- provider; this column records only that the link went out.
comment on column orders.deposit_link_sent is
    'A deposit link was texted. Not proof of payment.';

-- Sent and paid are separate on purpose. The agent can verify that it sent a
-- link; only the payment provider can say the money arrived, via a webhook.
alter table orders add column if not exists deposit_paid boolean not null default false;
alter table orders add column if not exists caller_id text;

comment on column orders.caller_id is
    'Carrier-supplied number the call came from (sip.phoneNumber). Null on web orders or when the caller withholds it. Unlike phone_number, the caller cannot choose this.';
