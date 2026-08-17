-- Hire Slice orders.
--
-- One row per *confirmed* order. The cart being built mid-call lives in
-- session.userdata and never reaches this table — fifteen turns of "actually
-- make that two" produce one row, written once at confirm_order.
--
-- Apply in the Supabase SQL editor.

create table if not exists orders (
    id              bigint generated always as identity primary key,
    code            text        not null unique,
    placed_at       timestamptz not null default now(),

    -- "phone" or "web": both transports run the same agent, so this is the only
    -- thing that distinguishes them once the order lands.
    channel         text        not null check (channel in ('phone', 'web')),
    room            text,

    customer_name   text        not null,
    phone_number    text        not null,
    fulfillment     text        not null check (fulfillment in ('pickup', 'delivery')),
    address         text,

    -- Line items as written at confirm time. Denormalized on purpose: this is a
    -- record of what was ordered at the price quoted, not a live join against a
    -- menu that may change.
    items           jsonb       not null,
    subtotal        numeric(8,2) not null,
    delivery_fee    numeric(8,2) not null default 0,
    total           numeric(8,2) not null,

    constraint delivery_needs_address
        check (fulfillment <> 'delivery' or address is not null)
);

create index if not exists orders_placed_at_idx on orders (placed_at desc);

-- The dashboard reads with the anon key, so RLS must be on with an explicit
-- policy. Read-only for anon: orders are written by the agent using the service
-- role key, which bypasses RLS.
alter table orders enable row level security;

drop policy if exists "orders are readable" on orders;
create policy "orders are readable"
    on orders for select
    to anon
    using (true);

-- Realtime: the dashboard subscribes to inserts so a confirmed order appears
-- while the caller is still on the line. Guarded so re-running this file is a
-- no-op rather than error 42710.
do $$
begin
    alter publication supabase_realtime add table orders;
exception
    when duplicate_object then null;
end
$$;
