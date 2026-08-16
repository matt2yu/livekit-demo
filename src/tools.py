"""Ordering tools.

Every mutating tool ends its return with a status directive ("| next: ...").
Tool-heavy voice flows drift without one, and it keeps the next step explicit
without a system prompt enumerating every branch.

Parameter enums are built from the menu tables, so an item the kitchen can't
make is rejected by the schema before the model can order it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Annotated

from livekit.agents import RunContext, ToolError, function_tool
from livekit.agents.beta.workflows import (
    GetAddressTask,
    GetNameTask,
    GetPhoneNumberTask,
)
from pydantic import Field

from menu import (
    DELIVERY_ETA,
    DELIVERY_FEE,
    DRINKS,
    PICKUP_ETA,
    PIZZAS,
    SAUCES,
    SIZES,
    TOPPINGS,
    Size,
    menu_summary,
    speak_price,
)
from order import Line, Order, order_code

logger = logging.getLogger("lucky-slice.tools")

PizzaName = Annotated[str, Field(json_schema_extra={"enum": list(PIZZAS)})]
DrinkName = Annotated[str, Field(json_schema_extra={"enum": list(DRINKS)})]
SauceName = Annotated[str, Field(json_schema_extra={"enum": list(SAUCES)})]
ToppingName = Annotated[str, Field(json_schema_extra={"enum": list(TOPPINGS)})]
SizeName = Annotated[Size, Field(json_schema_extra={"enum": list(SIZES)})]
OrderedName = Annotated[
    str, Field(json_schema_extra={"enum": [*PIZZAS, *DRINKS, *SAUCES]})
]


@dataclass
class Userdata:
    order: Order = field(default_factory=Order)


def _options(names) -> str:
    return ", ".join(names)


class OrderingTools:
    @function_tool
    async def get_menu(self, ctx: RunContext[Userdata]) -> str:
        """Read out what Lucky Slice sells. Use when the caller asks what's available,
        what the options are, or how much something costs."""
        return menu_summary()

    @function_tool
    async def add_pizza(
        self,
        ctx: RunContext[Userdata],
        name: PizzaName,
        size: SizeName,
        toppings: list[ToppingName] | None = None,
        qty: int = 1,
    ) -> str:
        """Add a pizza to the order.

        Ask for the size before calling this — never guess one. Examples:
        "a large pepperoni", "two small cheese pizzas with mushrooms".

        Args:
            name: Which pizza.
            size: small, medium, or large.
            toppings: Extra toppings beyond what the pizza already comes with.
            qty: How many of this exact pizza.
        """
        if name not in PIZZAS:
            raise ToolError(f"We don't have {name}. We have {_options(PIZZAS)}.")
        for topping in toppings or ():
            if topping not in TOPPINGS:
                raise ToolError(
                    f"We don't have {topping} as a topping. We have {_options(TOPPINGS)}."
                )

        order = ctx.userdata.order
        line = order.add(
            Line("pizza", name, size=size, toppings=tuple(toppings or ()), qty=qty)
        )
        return (
            f"Added {line.spoken()}. Running total {speak_price(order.total)}. "
            "| next: ask if they'd like anything else"
        )

    @function_tool
    async def add_drink(
        self, ctx: RunContext[Userdata], name: DrinkName, size: SizeName, qty: int = 1
    ) -> str:
        """Add a drink. Ask for the size before calling this.

        Args:
            name: Which drink.
            size: small, medium, or large.
            qty: How many.
        """
        if name not in DRINKS:
            raise ToolError(f"We don't have {name}. We have {_options(DRINKS)}.")

        order = ctx.userdata.order
        line = order.add(Line("drink", name, size=size, qty=qty))
        return (
            f"Added {line.spoken()}. Running total {speak_price(order.total)}. "
            "| next: ask if they'd like anything else"
        )

    @function_tool
    async def add_sauce(
        self, ctx: RunContext[Userdata], name: SauceName, qty: int = 1
    ) -> str:
        """Add a dipping sauce. Sauces come in one size.

        Args:
            name: Which sauce.
            qty: How many.
        """
        if name not in SAUCES:
            raise ToolError(f"We don't have {name} sauce. We have {_options(SAUCES)}.")

        order = ctx.userdata.order
        line = order.add(Line("sauce", name, qty=qty))
        return (
            f"Added {line.spoken()}. Running total {speak_price(order.total)}. "
            "| next: ask if they'd like anything else"
        )

    @function_tool
    async def remove_item(self, ctx: RunContext[Userdata], name: OrderedName) -> str:
        """Take something off the order. Use when the caller changes their mind."""
        order = ctx.userdata.order
        removed = order.remove(name)
        if removed is None:
            raise ToolError(f"There's no {name} on the order.")
        return (
            f"Removed {removed.spoken()}. Running total {speak_price(order.total)}. "
            "| next: ask if they'd like anything else"
        )

    @function_tool
    async def set_quantity(
        self, ctx: RunContext[Userdata], name: OrderedName, qty: int
    ) -> str:
        """Change how many of something is on the order — "actually make that two".

        Args:
            name: The item already on the order.
            qty: The new count. Zero removes it.
        """
        order = ctx.userdata.order
        line = order.set_quantity(name, qty)
        if line is None:
            raise ToolError(f"There's no {name} on the order.")
        if qty <= 0:
            return (
                f"Removed the {name}. Running total {speak_price(order.total)}. "
                "| next: ask if they'd like anything else"
            )
        return (
            f"Now {line.spoken()}. Running total {speak_price(order.total)}. "
            "| next: ask if they'd like anything else"
        )

    @function_tool
    async def order_summary(self, ctx: RunContext[Userdata]) -> str:
        """Read the whole order back with the total. Use before confirming, or when asked
        what's on the order so far."""
        return ctx.userdata.order.readback()

    @function_tool
    async def set_fulfillment(self, ctx: RunContext[Userdata], method: str) -> str:
        """Set the order to pickup or delivery.

        For delivery this collects the address, so don't ask for the address yourself.

        Args:
            method: Either "pickup" or "delivery".
        """
        if method not in ("pickup", "delivery"):
            raise ToolError('Fulfillment must be either "pickup" or "delivery".')

        order = ctx.userdata.order
        order.fulfillment = method

        if method == "pickup":
            return (
                f"Set to pickup, ready in {PICKUP_ETA}. "
                f"Total {speak_price(order.total)}. | next: collect their name and phone number"
            )

        result = await GetAddressTask(
            extra_instructions="This is a pizza delivery address. Include an apartment or unit number if there is one.",
            require_confirmation=True,
        )
        order.address = result.address
        return (
            f"Delivering to {result.address}, {DELIVERY_ETA}. "
            f"Delivery fee {speak_price(DELIVERY_FEE)}, total {speak_price(order.total)}. "
            "| next: collect their name and phone number"
        )

    @function_tool
    async def collect_contact(self, ctx: RunContext[Userdata]) -> str:
        """Collect the caller's name and phone number. Call this once, after the order
        and fulfillment are settled and before confirming."""
        order = ctx.userdata.order

        name = await GetNameTask(first_name=True)
        order.customer_name = name.first_name

        phone = await GetPhoneNumberTask(require_confirmation=True)
        order.phone_number = phone.phone_number

        return (
            f"Got it, {order.customer_name}. "
            "| next: read the full order back and get an explicit yes before confirming"
        )

    @function_tool
    async def confirm_order(self, ctx: RunContext[Userdata]) -> str:
        """Place the order. Only call this after reading the order back and hearing an
        explicit yes."""
        order = ctx.userdata.order
        missing = order.missing_for_confirm()
        if missing:
            raise ToolError(
                "Can't place the order yet — still need " + ", ".join(missing) + "."
            )

        order.confirmed_code = order_code()
        eta = DELIVERY_ETA if order.fulfillment == "delivery" else PICKUP_ETA
        logger.info(
            "order confirmed",
            extra={
                "code": order.confirmed_code,
                "total": order.total,
                "fulfillment": order.fulfillment,
            },
        )
        return (
            f"Order placed. The code is {' '.join(order.confirmed_code)}, "
            f"total {speak_price(order.total)}, ready in {eta}. "
            "| next: read back the code, thank them, and end the call"
        )
