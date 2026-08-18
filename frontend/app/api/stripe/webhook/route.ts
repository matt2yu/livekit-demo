import { NextResponse } from 'next/server';
import type Stripe from 'stripe';
import { getStripe, getSupabaseAdmin } from '@/lib/stripe';

// The signature is computed over the exact bytes Stripe sent, so the body must
// not be parsed or re-serialized before it is verified.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * The only thing in this application that may set `deposit_paid`.
 *
 * Everything before the `constructEventAsync` call is untrusted: anyone can POST
 * here. A body that does not verify against STRIPE_WEBHOOK_SECRET is a 400 and
 * no write. Were the browser able to set this flag instead, a prankster would
 * set it with curl and the kitchen would cook an unpaid catering order.
 *
 * In test mode a prankster can still complete checkout with a test card. Test
 * mode demonstrates the mechanism; live mode is where the money is real.
 */
export async function POST(req: Request) {
  const signature = req.headers.get('stripe-signature');
  const secret = process.env.STRIPE_WEBHOOK_SECRET;

  if (!secret) {
    console.error('STRIPE_WEBHOOK_SECRET is not set; refusing to trust the payload.');
    return NextResponse.json({ error: 'Webhook is not configured.' }, { status: 500 });
  }
  if (!signature) {
    return NextResponse.json({ error: 'Missing stripe-signature.' }, { status: 400 });
  }

  const body = await req.text();

  let event: Stripe.Event;
  try {
    // Async rather than sync: the sync path needs a synchronous crypto provider
    // and throws if one is not available, and the async one is correct everywhere.
    event = await getStripe().webhooks.constructEventAsync(body, signature, secret);
  } catch (e) {
    console.warn('Rejected an unverified Stripe webhook.', e);
    return NextResponse.json({ error: 'Bad signature.' }, { status: 400 });
  }

  if (event.type !== 'checkout.session.completed') {
    // 200, or Stripe retries an event we will never act on.
    return NextResponse.json({ received: true, ignored: event.type });
  }

  const session = event.data.object;
  const code = session.metadata?.order_code ?? session.client_reference_id;

  if (!code) {
    console.error('Verified checkout.session.completed carried no order code.', session.id);
    return NextResponse.json({ received: true, ignored: 'no order code' });
  }
  // Completed is not paid: an async payment method can complete the session and
  // settle later, and that later state arrives as its own event.
  if (session.payment_status !== 'paid') {
    return NextResponse.json({ received: true, ignored: session.payment_status });
  }

  const { error } = await getSupabaseAdmin()
    .from('orders')
    .update({ deposit_paid: true, stripe_session_id: session.id })
    .eq('code', code);

  if (error) {
    // 500 so Stripe retries. Setting a flag that is already set is a no-op, so
    // a redelivery is safe.
    console.error('Deposit cleared but the order row did not update.', code, error.message);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  console.info('Deposit paid.', code);
  return NextResponse.json({ received: true });
}
