"""Final-state grading for simulated calls.

The simulator judges the transcript; this judges the Order the agent actually
built. A polished conversation can still produce the wrong order, so a run
passes only if both agree. See scenarios.yaml for the expected_state shape.
"""

from __future__ import annotations

from livekit.agents import SimulationContext

from order import Order


def _describe(order: Order) -> str:
    if order.is_empty:
        return "empty order"
    return "; ".join(
        f"{line.qty}x {line.size or ''} {line.item}"
        f"{' +' + ','.join(sorted(line.toppings)) if line.toppings else ''}".strip()
        for line in order.lines
    )


def _describe_want(want: dict) -> str:
    return f"{want.get('size', '')} {want['item']}".strip()


def _line_problems(order: Order, expected_lines: list[dict]) -> list[str]:
    problems: list[str] = []
    # An order can hold a small and a large of the same pizza, so a line is
    # claimed once it's matched. Matching on the item name alone would score both
    # expectations against whichever line came first — the same mistake that made
    # remove_item take the wrong pizza.
    unclaimed = list(order.lines)
    for want in expected_lines:
        match = next(
            (
                line
                for line in unclaimed
                if line.item == want["item"]
                and ("size" not in want or line.size == want["size"])
            ),
            None,
        )
        if match is None:
            problems.append(f"missing {_describe_want(want)}")
            continue
        unclaimed.remove(match)
        if "size" in want and match.size != want["size"]:
            problems.append(
                f"{want['item']} size {match.size}, expected {want['size']}"
            )
        if "qty" in want and match.qty != want["qty"]:
            problems.append(f"{want['item']} qty {match.qty}, expected {want['qty']}")
        if "toppings" in want and sorted(match.toppings) != sorted(want["toppings"]):
            problems.append(
                f"{want['item']} toppings {sorted(match.toppings)}, "
                f"expected {sorted(want['toppings'])}"
            )
    return problems


async def on_simulation_end(ctx: SimulationContext) -> None:
    expected = ctx.userdata().get("expected_state")
    if not expected:
        return  # graded on the conversation alone

    session = ctx.job_context.primary_session
    order: Order = session.userdata.order
    problems: list[str] = []

    if "lines" in expected:
        problems += _line_problems(order, expected["lines"])
        if len(order.lines) != len(expected["lines"]):
            problems.append(
                f"{len(order.lines)} lines, expected {len(expected['lines'])}"
            )

    if "fulfillment" in expected and order.fulfillment != expected["fulfillment"]:
        problems.append(
            f"fulfillment {order.fulfillment}, expected {expected['fulfillment']}"
        )

    if "has_address" in expected:
        has = order.address is not None
        if has != expected["has_address"]:
            problems.append(
                "collected an address on a pickup order"
                if has
                else "no address on a delivery order"
            )

    if "confirmed" in expected:
        confirmed = order.confirmed_code is not None
        if confirmed != expected["confirmed"]:
            problems.append(
                "issued an order code without confirmation"
                if confirmed
                else "never issued an order code"
            )

    if problems:
        ctx.fail(reason=f"{'; '.join(problems)} (final order: {_describe(order)})")
