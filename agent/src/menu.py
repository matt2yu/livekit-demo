"""Hire Slice menu — the single source of truth for pricing and tool schemas.

Tool parameter enums are built from these tables at import time, so an item the
kitchen can't make never reaches the model as a valid choice.
"""

from __future__ import annotations

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

DELIVERY_FEE = 3.99

PICKUP_ETA = "about twenty minutes"
DELIVERY_ETA = "about forty-five minutes"


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
    """Speak-friendly menu, used by the get_menu tool."""
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
