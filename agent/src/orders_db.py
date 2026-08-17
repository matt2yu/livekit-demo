"""Writes confirmed orders to Supabase over PostgREST.

REST rather than a Postgres driver: the agent runs in an ephemeral container
that scales to zero, so a connection pool is the wrong shape. This also uses the
job-scoped aiohttp session LiveKit prescribes for tools that call HTTP APIs.

Writes use the service-role key and bypass RLS. That key must never reach the
frontend — the dashboard reads with the anon key under a read-only policy.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
from livekit.agents import utils

from order import Order, order_code

logger = logging.getLogger("hire-slice.orders_db")

# Short on purpose: this runs inside confirm_order, the most latency-sensitive
# moment of the call. A caller waiting on a hung database is worse than a caller
# hearing that the order didn't go through.
_TIMEOUT = aiohttp.ClientTimeout(total=3)

# Postgres unique_violation, surfaced by PostgREST as 409.
_DUPLICATE_KEY = "23505"
_CODE_RETRIES = 3


def is_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def _row(order: Order, *, channel: str, room: str | None) -> dict[str, Any]:
    return {
        "code": order.confirmed_code,
        "channel": channel,
        "room": room,
        "customer_name": order.customer_name,
        "phone_number": order.phone_number,
        "fulfillment": order.fulfillment,
        "address": order.address,
        "items": [
            {
                "category": line.category,
                "item": line.item,
                "size": line.size,
                "toppings": list(line.toppings),
                "qty": line.qty,
                # Unit price is copied, not referenced: this is what the caller was
                # quoted, and it must not move if the menu is repriced later.
                "unit_price": round(line.unit_price, 2),
            }
            for line in order.lines
        ],
        "subtotal": round(order.subtotal, 2),
        "delivery_fee": round(order.delivery_fee, 2),
        "total": order.total,
    }


async def save_order(order: Order, *, channel: str, room: str | None = None) -> bool:
    """Persist a confirmed order. Returns False if it didn't land.

    Never raises: the caller-facing decision about what to say lives in the tool,
    not here.

    On a code collision the order code is regenerated and retried. Codes are four
    base-36 characters, so clashes are rare but not impossible, and telling a
    caller their order failed because of a random string collision would be a
    poor trade.
    """
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        logger.warning("supabase not configured; order not persisted")
        return False

    endpoint = f"{url.rstrip('/')}/rest/v1/orders"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    for attempt in range(_CODE_RETRIES):
        try:
            session = utils.http_context.http_session()
            async with session.post(
                endpoint,
                json=_row(order, channel=channel, room=room),
                headers=headers,
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status < 300:
                    return True

                body = await resp.text()
                if resp.status == 409 and _DUPLICATE_KEY in body:
                    order.confirmed_code = order_code()
                    logger.warning(
                        "order code collision; retrying",
                        extra={"attempt": attempt + 1, "code": order.confirmed_code},
                    )
                    continue

                logger.error(
                    "supabase rejected order",
                    extra={"status": resp.status, "body": body[:400]},
                )
                return False
        except Exception:
            logger.exception("failed to persist order")
            return False

    logger.error("gave up after repeated order code collisions")
    return False
