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

import orders_db
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
from order import AmbiguousItemError, Line, Order, order_code

logger = logging.getLogger("hire-slice.tools")

PizzaName = Annotated[str, Field(json_schema_extra={"enum": list(PIZZAS)})]
DrinkName = Annotated[str, Field(json_schema_extra={"enum": list(DRINKS)})]
SauceName = Annotated[str, Field(json_schema_extra={"enum": list(SAUCES)})]
ToppingName = Annotated[str, Field(json_schema_extra={"enum": list(TOPPINGS)})]
SizeName = Annotated[Size, Field(json_schema_extra={"enum": list(SIZES)})]
# Optional because the size is only needed to break a tie. See the note on
# _strict_tool_schema in agent.py for why this can't be `SizeName | None`.
OptionalSizeName = Annotated[str, Field(json_schema_extra={"enum": list(SIZES)})]
OrderedName = Annotated[
    str, Field(json_schema_extra={"enum": [*PIZZAS, *DRINKS, *SAUCES]})
]


@dataclass
class Userdata:
    order: Order = field(default_factory=Order)
    # Set from the room name at session start. Phone calls land in rooms the SIP
    # dispatch rule prefixes with "call-"; everything else arrived over WebRTC.
    room: str | None = None
    # sip.phoneNumber off the SIP participant: the number the call actually came
    # from, supplied by the carrier rather than by the caller. The number a caller
    # speaks is whatever they choose to say; this one they had to dial from.
    caller_id: str | None = None
    # The large request the tool last refused, and how much conversation had
    # happened when it did. See _guard_quantity.
    awaiting_confirmation: tuple | None = None
    refused_at_turn: int = -1

    @property
    def channel(self) -> str:
        return "phone" if (self.room or "").startswith("call-") else "web"


def _options(names) -> str:
    return ", ".join(names)


# Three tiers, because "how many" has three different answers.
#
# Under ten, just add it. A phone line turns "two" into "twenty" often enough
# that ten or more is worth hearing back first — so the tool refuses until the
# agent has confirmed it out loud, and no prompt drift can put an unconfirmed
# twenty on the order.
#
# Past the kitchen's capacity it stops being an ASAP order. It is not refused —
# forty pizzas is good business — but it gets booked for a time and backed by a
# deposit instead of promised in twenty minutes. confirm_order enforces both.
_CONFIRM_QTY = 10

_NEXT = "| next: ask if they'd like anything else"


def _guard_quantity(ctx: RunContext[Userdata], request: tuple, qty: int) -> None:
    """Refuse a large quantity until the caller has actually been asked.

    Deliberately not a `confirmed: bool` the model passes in. It set that flag on
    its very first call, having asked nobody — a parameter the model fills in is a
    claim, not a control. So the tool keeps its own record: the first attempt at a
    large quantity always fails, and the retry is only honoured once the caller has
    said something in between. The agent cannot talk its way past this.
    """
    if qty < _CONFIRM_QTY:
        return

    data = ctx.userdata
    turn = len(ctx.session.history.items)
    already_asked = (
        data.awaiting_confirmation == request and turn > data.refused_at_turn
    )

    if already_asked:
        data.awaiting_confirmation = None
        return

    data.awaiting_confirmation = request
    data.refused_at_turn = turn
    raise ToolError(
        f"Nothing has been added. Tell the caller you have {qty} and ask whether "
        f"that is really the number they want. Wait for them to answer — then, "
        f"if they say yes, call this again exactly as before."
    )


def _added(order: Order, line: Line) -> str:
    said = f"Added {line.spoken()}. Running total {speak_price(order.total)}. "
    if order.is_catering:
        return said + (
            f"That is {order.item_count} items, which is a catering order. "
            f"| next: tell them an order this size needs {order.lead_time} and ask "
            f"what time they would like it, then call schedule_catering"
        )
    return said + _NEXT


def _which_one(exc: AmbiguousItemError) -> ToolError:
    sizes = " and a ".join(exc.sizes)
    return ToolError(
        f"There's a {sizes} {exc.item} on the order. Ask which one they mean, "
        f"then call this again with that size."
    )


class OrderingTools:
    @function_tool
    async def get_menu(self, ctx: RunContext[Userdata]) -> str:
        """Read out what Hire Slice sells. Use when the caller asks what's available,
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
        _guard_quantity(ctx, ("pizza", name, size, tuple(toppings or ()), qty), qty)
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
        return _added(order, line)

    @function_tool
    async def add_drink(
        self,
        ctx: RunContext[Userdata],
        name: DrinkName,
        size: SizeName,
        qty: int = 1,
    ) -> str:
        """Add a drink. Ask for the size before calling this.

        Args:
            name: Which drink.
            size: small, medium, or large.
            qty: How many.
        """
        _guard_quantity(ctx, ("drink", name, size, qty), qty)
        if name not in DRINKS:
            raise ToolError(f"We don't have {name}. We have {_options(DRINKS)}.")

        order = ctx.userdata.order
        line = order.add(Line("drink", name, size=size, qty=qty))
        return _added(order, line)

    @function_tool
    async def add_sauce(
        self,
        ctx: RunContext[Userdata],
        name: SauceName,
        qty: int = 1,
    ) -> str:
        """Add a dipping sauce. Sauces come in one size.

        Args:
            name: Which sauce.
            qty: How many.
        """
        _guard_quantity(ctx, ("sauce", name, qty), qty)
        if name not in SAUCES:
            raise ToolError(f"We don't have {name} sauce. We have {_options(SAUCES)}.")

        order = ctx.userdata.order
        line = order.add(Line("sauce", name, qty=qty))
        return _added(order, line)

    @function_tool
    async def remove_item(
        self,
        ctx: RunContext[Userdata],
        name: OrderedName,
        size: OptionalSizeName = "",
    ) -> str:
        """Take something off the order. Use when the caller changes their mind.

        Args:
            name: The item already on the order.
            size: Only needed when that item is on the order in more than one
                size. Leave it out otherwise.
        """
        order = ctx.userdata.order
        try:
            removed = order.remove(name, size or None)
        except AmbiguousItemError as exc:
            raise _which_one(exc) from None
        if removed is None:
            raise ToolError(f"There's no {size or ''} {name} on the order.".strip())
        return f"Removed {removed.spoken()}. Running total {speak_price(order.total)}. {_NEXT}"

    @function_tool
    async def set_quantity(
        self,
        ctx: RunContext[Userdata],
        name: OrderedName,
        qty: int,
        size: OptionalSizeName = "",
    ) -> str:
        """Change how many of something is on the order — "actually make that two".

        Args:
            name: The item already on the order.
            qty: The new count. Zero removes it.
            size: Only needed when that item is on the order in more than one
                size. Leave it out otherwise.
        """
        _guard_quantity(ctx, ("set", name, size, qty), qty)
        order = ctx.userdata.order
        try:
            line = order.set_quantity(name, qty, size or None)
        except AmbiguousItemError as exc:
            raise _which_one(exc) from None
        if line is None:
            raise ToolError(f"There's no {size or ''} {name} on the order.".strip())
        if qty <= 0:
            return (
                f"Removed the {name}. Running total {speak_price(order.total)}. {_NEXT}"
            )
        return f"Now {line.spoken()}. Running total {speak_price(order.total)}. {_NEXT}"

    @function_tool
    async def clear_order(self, ctx: RunContext[Userdata]) -> str:
        """Take everything off the order and start the food over. Use when the caller
        says to cancel it all or start again. Their name, number, and address are kept."""
        order = ctx.userdata.order
        if order.is_empty:
            raise ToolError("There's nothing on the order yet.")
        order.clear()
        return "Cleared the order. | next: ask what they'd like"

    @function_tool
    async def order_summary(self, ctx: RunContext[Userdata]) -> str:
        """Read the whole order back with the total. Use before confirming, or when asked
        what's on the order so far."""
        order = ctx.userdata.order
        order.summarized_state = order.priced_state
        return order.readback()

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

        try:
            result = await GetAddressTask(
                extra_instructions="This is a pizza delivery address. Include an apartment or unit number if there is one.",
                require_confirmation=True,
            )
        except Exception:
            # The nested task can be cancelled mid-capture. Roll fulfillment back so
            # the order isn't left as delivery-with-no-address, and let the agent
            # recover by asking again rather than dying here.
            order.fulfillment = None
            logger.warning("address capture did not complete", exc_info=True)
            raise ToolError(
                "The address didn't come through. Apologize, then ask whether they want "
                "delivery or pickup and try again."
            ) from None

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
    async def schedule_catering(self, ctx: RunContext[Userdata], when: str) -> str:
        """Book a catering order for a time. Only for orders large enough that a tool
        has told you they are catering.

        Args:
            when: The time the caller asked for, in their own words — "tomorrow at
                six", "Saturday lunchtime". Confirm it with them before calling.
        """
        order = ctx.userdata.order
        if not order.is_catering:
            raise ToolError(
                "This order isn't large enough to need booking. Carry on as normal."
            )
        order.scheduled_for = when
        return (
            f"Booked for {when}. | next: tell them a deposit is needed to hold a "
            f"catering order, and call send_deposit_link"
        )

    @function_tool
    async def send_deposit_link(self, ctx: RunContext[Userdata]) -> str:
        """Text the caller a link to pay the deposit on a catering order. Use their
        collected phone number — never ask for card details on the call."""
        order = ctx.userdata.order
        if not order.is_catering:
            raise ToolError("No deposit is needed for an order this size.")
        # Prefer the verified caller ID over the spoken one. A prank order is only
        # worth placing if the deposit can be aimed at whoever actually rang.
        send_to = ctx.userdata.caller_id or order.phone_number
        if not send_to:
            raise ToolError(
                "Collect their phone number first — the link has to go somewhere."
            )
        # Stubbed. A real send is an HTTP call to a messaging provider from here,
        # the same shape as orders_db: LiveKit has no SMS of its own, its telephony
        # is SIP voice. Sent is not paid — see Order.deposit_link_sent.
        order.deposit_link_sent = True
        logger.info(
            "deposit link queued",
            extra={"to": send_to, "verified": ctx.userdata.caller_id is not None},
        )
        return (
            "Deposit link sent to their number. | next: read the order back with the "
            "time, and get an explicit yes before confirming"
        )

    @function_tool
    async def confirm_order(self, ctx: RunContext[Userdata]) -> str:
        """Place the order. Only call this after reading the order back and hearing an
        explicit yes."""
        # Placing the order can't be rolled back — a caller talking over the agent
        # must not leave it half-committed.
        ctx.disallow_interruptions()

        order = ctx.userdata.order
        missing = order.missing_for_confirm()
        if missing:
            raise ToolError(
                "Can't place the order yet — still need " + ", ".join(missing) + "."
            )
        if order.readback_is_stale:
            # The order changed since it was last read back, so the total the
            # caller agreed to isn't the total they'd be charged.
            raise ToolError(
                "The order has changed since you last read it back. Call order_summary, "
                "read out exactly what it returns, and get a fresh yes before confirming."
            )

        order.confirmed_code = order_code()

        if orders_db.is_configured():
            saved = await orders_db.save_order(
                order,
                channel=ctx.userdata.channel,
                room=ctx.userdata.room,
                caller_id=ctx.userdata.caller_id,
            )
            if not saved:
                # The kitchen never got it, so the caller must not be told it's coming.
                order.confirmed_code = None
                raise ToolError(
                    "The order didn't go through to the kitchen. Apologize and offer to try again."
                )

        # A booked catering order is ready when it was booked for, not in twenty
        # minutes. Promising the ASAP window here would undo the whole exchange.
        if order.scheduled_for:
            eta = f"time for {order.scheduled_for}"
        else:
            eta = DELIVERY_ETA if order.fulfillment == "delivery" else PICKUP_ETA
        logger.info(
            "order confirmed",
            extra={
                "code": order.confirmed_code,
                "total": order.total,
                "fulfillment": order.fulfillment,
                "channel": ctx.userdata.channel,
            },
        )
        return (
            f"Order placed. The code is {' '.join(order.confirmed_code)}, "
            f"total {speak_price(order.total)}, ready in {eta}. "
            "| next: read back the code, thank them, and end the call"
        )
