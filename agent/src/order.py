"""Order state for a single call."""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from typing import Literal

from menu import (
    CATERING_FROM,
    DELIVERY_FEE,
    DRINKS,
    PIZZAS,
    SAUCES,
    TOPPINGS,
    Size,
    catering_lead,
    speak_price,
)

Fulfillment = Literal["pickup", "delivery"]

# In production a catering order should not be placed until the deposit has
# actually cleared, which means a webhook from the payment provider setting
# Order.deposit_paid. Nothing issues that webhook here, so the demo gates on the
# link having been sent instead. This is the one line that changes when a real
# payment provider is wired in — and the agent still never claims a payment it
# hasn't been told about.
REQUIRE_DEPOSIT_PAID = False


def order_code() -> str:
    """Short code a caller can repeat back at the counter."""
    return "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)
    )


class AmbiguousItemError(Exception):
    """The item names more than one line, and nothing said which was meant.

    Raised rather than returning the first match: an order can hold a small and
    a large of the same pizza, and silently picking one removes the wrong pizza
    while telling the caller it removed the right one.
    """

    def __init__(self, item: str, sizes: list[str]) -> None:
        self.item = item
        self.sizes = sizes
        super().__init__(f"{item} is on the order in {len(sizes)} sizes: {sizes}")


@dataclass
class Line:
    category: Literal["pizza", "drink", "sauce"]
    item: str
    size: Size | None = None
    toppings: tuple[str, ...] = ()
    qty: int = 1

    @property
    def unit_price(self) -> float:
        if self.category == "pizza":
            base = PIZZAS[self.item].price(self.size)
            return base + sum(TOPPINGS[t].price for t in self.toppings)
        if self.category == "drink":
            return DRINKS[self.item].price(self.size)
        return SAUCES[self.item].price

    @property
    def total(self) -> float:
        return self.unit_price * self.qty

    def matches(self, other: Line) -> bool:
        return (
            self.category == other.category
            and self.item == other.item
            and self.size == other.size
            and sorted(self.toppings) == sorted(other.toppings)
        )

    def spoken(self) -> str:
        parts = []
        if self.qty > 1:
            parts.append(str(self.qty))
        if self.size:
            parts.append(self.size)
        parts.append(self.item)
        text = " ".join(parts)
        if self.toppings:
            text += " with " + " and ".join(self.toppings)
        return text


@dataclass
class Order:
    lines: list[Line] = field(default_factory=list)
    fulfillment: Fulfillment | None = None
    customer_name: str | None = None
    phone_number: str | None = None
    address: str | None = None
    confirmed_code: str | None = None
    # The state as it stood the last time order_summary spoke it. See priced_state.
    summarized_state: tuple | None = None
    # When the caller wants a catering order, in their own words. Deliberately not
    # parsed into a timestamp: "the Saturday after next, around six" is something a
    # human reads off a ticket, and guessing a datetime from it would invent detail
    # the caller never gave.
    scheduled_for: str | None = None
    # Two states, deliberately not one. Sending a link is something this agent can
    # do and verify; being paid is something only the payment provider can tell us,
    # via a webhook that isn't wired up. Collapsing them would mean the agent
    # asserting a payment it has no evidence for — the same class of bug as claiming
    # an order was placed when the write failed.
    deposit_link_sent: bool = False
    deposit_paid: bool = False

    @property
    def item_count(self) -> int:
        """Everything on the order, counted. Kitchen capacity is per order, not per
        line — twenty cheese and twenty pepperoni is still forty pizzas."""
        return sum(line.qty for line in self.lines)

    @property
    def is_catering(self) -> bool:
        return self.item_count >= CATERING_FROM

    @property
    def lead_time(self) -> str:
        return catering_lead(self.item_count)

    @property
    def priced_state(self) -> tuple:
        """Everything that determines the total.

        confirm_order compares this against summarized_state, so a total the
        caller never heard can't be confirmed. The agent had been quoting figures
        it worked out itself; a prompt rule alone didn't hold.
        """
        return (
            tuple(
                (
                    line.category,
                    line.item,
                    line.size,
                    tuple(sorted(line.toppings)),
                    line.qty,
                )
                for line in self.lines
            ),
            self.fulfillment,
        )

    @property
    def readback_is_stale(self) -> bool:
        return self.summarized_state != self.priced_state

    def add(self, line: Line) -> Line:
        for existing in self.lines:
            if existing.matches(line):
                existing.qty += line.qty
                return existing
        self.lines.append(line)
        return line

    def find(self, item: str, size: Size | None = None) -> Line | None:
        """The one line matching this item, or None.

        Raises AmbiguousItemError when the item alone names several lines and no size
        narrows it down.
        """
        matches = [line for line in self.lines if line.item == item]
        if size is not None:
            matches = [line for line in matches if line.size == size]
        elif len(matches) > 1:
            raise AmbiguousItemError(item, [line.size for line in matches if line.size])
        return matches[0] if matches else None

    def remove(self, item: str, size: Size | None = None) -> Line | None:
        line = self.find(item, size)
        if line is not None:
            self.lines.remove(line)
        return line

    def set_quantity(
        self, item: str, qty: int, size: Size | None = None
    ) -> Line | None:
        line = self.find(item, size)
        if line is None:
            return None
        if qty <= 0:
            self.lines.remove(line)
        else:
            line.qty = qty
        return line

    def clear(self) -> None:
        """Drop the food, keep the caller.

        Starting the order over is not the same as forgetting who they are or
        where it's going — re-asking for all of that is exactly the behaviour
        the prompt forbids.
        """
        self.lines.clear()

    @property
    def subtotal(self) -> float:
        return sum(line.total for line in self.lines)

    @property
    def delivery_fee(self) -> float:
        # There is nothing to deliver until something is on the order, so an
        # emptied cart must not still quote the fee.
        if self.is_empty or self.fulfillment != "delivery":
            return 0.0
        return DELIVERY_FEE

    @property
    def total(self) -> float:
        return round(self.subtotal + self.delivery_fee, 2)

    @property
    def is_empty(self) -> bool:
        return not self.lines

    def missing_for_confirm(self) -> list[str]:
        """What still has to be collected before the order can be placed."""
        missing = []
        if self.is_empty:
            missing.append("at least one item")
        if self.fulfillment is None:
            missing.append("pickup or delivery")
        if not self.customer_name:
            missing.append("a name")
        if not self.phone_number:
            missing.append("a phone number")
        if self.fulfillment == "delivery" and not self.address:
            missing.append("a delivery address")
        if self.is_catering:
            # A catering order with no agreed time, or that nobody has committed
            # money to, is how a prank becomes a four-figure ticket for the kitchen.
            if not self.scheduled_for:
                missing.append("a time to have it ready")
            if REQUIRE_DEPOSIT_PAID and not self.deposit_paid:
                missing.append("the deposit to be paid")
            elif not self.deposit_link_sent:
                missing.append("a deposit")
        return missing

    def readback(self) -> str:
        if self.is_empty:
            return "The order is empty."
        items = "; ".join(line.spoken() for line in self.lines)
        parts = [items]
        if self.fulfillment == "delivery":
            parts.append(
                f"for delivery, with a {speak_price(DELIVERY_FEE)} delivery fee"
            )
        elif self.fulfillment == "pickup":
            parts.append("for pickup")
        return ", ".join(parts) + f". Total is {speak_price(self.total)}."
