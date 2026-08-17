import { NextResponse } from 'next/server';
import { getStripe, getSupabaseAdmin } from '@/lib/stripe';
import { type Order, depositDue, isCatering } from '@/lib/supabase';

/**
 * Opens a Stripe Checkout session for a catering deposit.
 *
 * The browser sends a code and nothing else. The amount is read from the order
 * row here — a request body carrying its own price is a request body that pays
 * a dollar for a four-hundred dollar booking.
 */
export async function POST(req: Request) {
  let code: unknown;
  try {
    ({ code } = await req.json());
  } catch {
    return NextResponse.json({ error: 'Expected a JSON body.' }, { status: 400 });
  }

  if (typeof code !== 'string' || !/^[A-Z0-9]{4}$/.test(code)) {
    return NextResponse.json({ error: 'Not an order code.' }, { status: 400 });
  }

  const supabase = getSupabaseAdmin();
  const { data, error } = await supabase.from('orders').select('*').eq('code', code).maybeSingle();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  if (!data) {
    return NextResponse.json({ error: 'No order with that code.' }, { status: 404 });
  }

  const order = data as Order;
  if (!isCatering(order)) {
    return NextResponse.json({ error: 'That order takes no deposit.' }, { status: 409 });
  }
  if (order.deposit_paid) {
    return NextResponse.json({ error: 'That deposit is already paid.' }, { status: 409 });
  }

  const origin = new URL(req.url).origin;
  const session = await getStripe().checkout.sessions.create({
    mode: 'payment',
    line_items: [
      {
        quantity: 1,
        price_data: {
          currency: 'usd',
          unit_amount: Math.round(depositDue(order) * 100),
          product_data: {
            name: `Catering deposit — order ${order.code}`,
            description: `${order.customer_name}, for ${order.scheduled_for}`,
          },
        },
      },
    ],
    // Both, because the webhook reads whichever survives: metadata is ours,
    // client_reference_id is what the Stripe dashboard shows a human.
    client_reference_id: order.code,
    metadata: { order_code: order.code },
    success_url: `${origin}/pay/${order.code}?paid=1`,
    cancel_url: `${origin}/pay/${order.code}`,
  });

  // Written before the redirect so an abandoned checkout still leaves a trail.
  // deposit_paid stays false — only the webhook may move it.
  await supabase.from('orders').update({ stripe_session_id: session.id }).eq('code', order.code);

  if (!session.url) {
    return NextResponse.json({ error: 'Stripe returned no checkout URL.' }, { status: 502 });
  }

  return NextResponse.json({ url: session.url });
}
