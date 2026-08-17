"""Hire Slice menu — the single source of truth for pricing and tool schemas.

Tool parameter enums are built from these tables at import time, so an item the
kitchen can't make never reaches the model as a valid choice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Size = Literal["small", "medium", "large"]

SIZES: tuple[Size, ...] = ("small", "medium", "large")


@dataclass(frozen=True)
class SizedItem:
    name: str
    prices: dict[Size, float]

    def price(self, size: Size) -> float:
        return self.prices[size]


@dataclass(frozen=True)
class FlatItem:
    name: str
    price: float


PIZZAS: dict[str, SizedItem] = {
    "cheese": SizedItem("cheese", {"small": 11.00, "medium": 14.00, "large": 17.00}),
    "pepperoni": SizedItem(
        "pepperoni", {"small": 12.50, "medium": 15.50, "large": 18.50}
    ),
    "margherita": SizedItem(
        "margherita", {"small": 12.50, "medium": 15.50, "large": 18.50}
    ),
}

DRINKS: dict[str, SizedItem] = {
    "water": SizedItem("water", {"small": 1.50, "medium": 2.00, "large": 2.50}),
    "coke": SizedItem("coke", {"small": 2.00, "medium": 2.50, "large": 3.00}),
    "sprite": SizedItem("sprite", {"small": 2.00, "medium": 2.50, "large": 3.00}),
}

SAUCES: dict[str, FlatItem] = {
    "ranch": FlatItem("ranch", 0.75),
    "garlic": FlatItem("garlic", 0.75),
    "marinara": FlatItem("marinara", 0.75),
    "bbq": FlatItem("bbq", 0.75),
}

TOPPINGS: dict[str, FlatItem] = {
    "mushrooms": FlatItem("mushrooms", 1.50),
    "onions": FlatItem("onions", 1.50),
    "olives": FlatItem("olives", 1.50),
    "peppers": FlatItem("peppers", 1.50),
    "sausage": FlatItem("sausage", 1.50),
    "extra cheese": FlatItem("extra cheese", 1.50),
}

# A fictional shop. The address is invented — it is not a real business — but it
# sits in 77096 so the delivery area below is geographically coherent.
SHOP_NAME = "Hire Slice"
SHOP_ADDRESS = "4715 Beechnut Street, Houston, Texas 77096"
SHOP_CROSS_STREET = "just off South Braeswood"

# Where we deliver, as data rather than as a hope the model gets it right — the
# same reason the menu drives the tool enums.
#
# The honest limit: a ZIP is not a radius. These are the ring around the shop,
# roughly five miles, which is what the forty-five minute delivery estimate can
# actually support. A production version swaps this set for a geocoder and a real
# distance check, which is one function — the rest of the design does not move.
DELIVERY_ZIPS = frozenset(
    {
        "77096",  # the shop itself
        "77035",
        "77071",
        "77074",
        "77401",
        "77025",
        "77081",
        "77045",
        "77031",
    }
)

_ZIP = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def serves(address: str) -> bool:
    """Whether we deliver to this address.

    Matches the last five-digit group: house numbers run to five digits often
    enough that taking the first one would refuse real addresses.
    """
    found = _ZIP.findall(address)
    return bool(found) and found[-1] in DELIVERY_ZIPS


DELIVERY_FEE = 3.99

PICKUP_ETA = "about twenty minutes"
DELIVERY_ETA = "about forty-five minutes"

# Past this many items it stops being something the kitchen makes while the
# caller waits. It isn't refused — a forty-pizza order is good business — but it
# has to be booked for a time rather than promised in twenty minutes.
CATERING_FROM = 25


def catering_lead(count: int) -> str:
    """How much notice the kitchen needs for an order this size.

    One oven does not care that the caller is in a hurry. Quoting a flat lead
    time would mean promising two hundred pizzas as readily as thirty.
    """
    if count >= 100:
        return "a full day's notice"
    if count >= 50:
        return "about six hours"
    return "about three hours"


def speak_price(amount: float) -> str:
    """Render a price the way a person says it, for TTS.

    17.00 -> 'seventeen dollars', 12.50 -> 'twelve fifty', 0.75 -> 'seventy-five cents',
    22.05 -> 'twenty-two oh five' ('twenty-two five' would be heard as 22.50).
    """
    total_cents = round(amount * 100)
    dollars, cents = divmod(total_cents, 100)
    if cents == 0:
        unit = "dollar" if dollars == 1 else "dollars"
        return f"{_say_number(dollars)} {unit}"
    if dollars == 0:
        return f"{_say_number(cents)} cents"
    if cents < 10:
        return f"{_say_number(dollars)} oh {_say_number(cents)}"
    return f"{_say_number(dollars)} {_say_number(cents)}"


_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)


def _say_number(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] if ones == 0 else f"{_TENS[tens]}-{_ONES[ones]}"
    hundreds, rest = divmod(n, 100)
    head = f"{_ONES[hundreds]} hundred"
    return head if rest == 0 else f"{head} {_say_number(rest)}"


def menu_summary() -> str:
    """Speak-friendly menu, used by the get_info tool."""
    pizzas = ", ".join(p.name for p in PIZZAS.values())
    drinks = ", ".join(d.name for d in DRINKS.values())
    sauces = ", ".join(s.name for s in SAUCES.values())
    toppings = ", ".join(t.name for t in TOPPINGS.values())
    return (
        f"Pizzas: {pizzas}, each in small, medium, or large. "
        f"Extra toppings are a dollar fifty each: {toppings}. "
        f"Drinks: {drinks}, also in three sizes. "
        f"Dipping sauces at {speak_price(0.75)}: {sauces}."
    )
