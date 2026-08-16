"""Order state for a single call."""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass, field
from typing import Literal

from menu import DELIVERY_FEE, DRINKS, PIZZAS, SAUCES, TOPPINGS, Size, speak_price

Fulfillment = Literal["pickup", "delivery"]


def order_code() -> str:
    """Short code a caller can repeat back at the counter."""
    return "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)
    )


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

    def add(self, line: Line) -> Line:
        for existing in self.lines:
            if existing.matches(line):
                existing.qty += line.qty
                return existing
        self.lines.append(line)
        return line

    def find(self, item: str) -> Line | None:
        for line in self.lines:
            if line.item == item:
                return line
        return None

    def remove(self, item: str) -> Line | None:
        line = self.find(item)
        if line is not None:
            self.lines.remove(line)
        return line

    def set_quantity(self, item: str, qty: int) -> Line | None:
        line = self.find(item)
        if line is None:
            return None
        if qty <= 0:
            self.lines.remove(line)
        else:
            line.qty = qty
        return line

    @property
    def subtotal(self) -> float:
        return sum(line.total for line in self.lines)

    @property
    def delivery_fee(self) -> float:
        return DELIVERY_FEE if self.fulfillment == "delivery" else 0.0

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
