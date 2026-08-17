import asyncio
import logging
import textwrap
from datetime import datetime

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    UserStateChangedEvent,
    cli,
    inference,
    room_io,
)
from livekit.agents.beta.tools import EndCallTool
from livekit.plugins import ai_coustics, anthropic

from menu import SHOP_NAME
from simulation import on_simulation_end
from tools import OrderingTools, Userdata

logger = logging.getLogger("agent")

load_dotenv(".env.local")


def _llm() -> anthropic.LLM:
    """The one place the model and its schema mode are chosen.

    Pinned: livekit-plugins-anthropic suppresses the trailing assistant-turn prefill
    only for models in its _NO_PREFILL_PATTERNS. Claude 4.6+ rejects prefills with a
    400, so a newer model id falls through and fails at runtime.

    Caching matters more here than it looks: the system prompt and ten tool
    schemas are ~2,600 tokens of byte-identical prefix re-sent on every turn of
    every call. It is also why the date above carries no clock time — caching is
    a prefix match, and a timestamp to the minute at the front of the prompt
    would invalidate the whole thing every sixty seconds, leaving only the 1.25x
    write premium and no reads.

    Strict tool schemas are off because they follow the OpenAI convention — every
    property forced into `required`, with a null sentinel added for the ones that
    have defaults. For a scalar enum parameter that yields
    `{"type": ["string", "null"], "enum": [...]}`, which Anthropic's validator
    rejects outright with a 400. Verified against the live API: the same tool is
    accepted when the union is left as `anyOf`. Any optional enum parameter hits
    this, so it is a property of the pairing, not of one tool.
    """
    return anthropic.LLM(
        model="claude-sonnet-4-6",
        caching="ephemeral",
        _strict_tool_schema=False,
    )


class HireSliceAgent(Agent, OrderingTools):
    def __init__(self) -> None:
        # Without this the agent has no way to hang up: every completed order
        # holds the line open until the caller does it, and inbound minutes are
        # the tightest budget this project has.
        end_call = EndCallTool(
            extra_description=(
                "End the call once the order is placed and the caller has heard "
                "their code and said goodbye, or when the caller says goodbye "
                "without ordering. Also end it if the caller is abusive after "
                "you have already asked them once to stop. Never end a call "
                "because the caller is annoyed or the order is taking a while."
            ),
            end_instructions="Thank them warmly, briefly, and say goodbye.",
        )
        super().__init__(
            tools=end_call.tools,
            llm=_llm(),
            instructions=textwrap.dedent(
                f"""\
                You take phone and web orders for Hire Slice, a pizzeria. Today is {datetime.now():%A, %B %-d, %Y}.

                # Voice

                - Plain text only. No markdown, lists, or symbols — everything you write is spoken aloud.
                - One to three sentences. Ask one question at a time.
                - Say prices as words, the way the tools give them back: "twelve fifty", not "$12.50".
                - Never say a tool name, a parameter, or anything after the "|" in a tool's reply. That part is for you.

                # Taking the order

                - Never invent menu items, toppings, or prices. Everything you say about the menu comes from a tool.
                - When the caller names a pizza, check whether they already gave a size. If they did, call add_item straight away and say nothing about size. Only ask for the size when they left it out.
                - Toppings are optional and default to none. Add them only if the caller brings them up. Never ask about toppings.
                - We sell pizzas, drinks, and dipping sauces. Nothing else — there are no sides, salads, or desserts.
                - After each item goes on, ask if they'd like anything else, and keep taking items for as long as they keep naming them. A second and third pizza are just more items — don't suggest anything while they're still ordering.
                - The one moment to suggest something is when they say they're done adding food. If there's no drink or sauce on the order by then, offer one, once. If they decline, or they already have one, go straight to pickup or delivery and never ask again.
                - The suggestion never delays finishing the order. If they ask you to place it, or the order is still missing something it needs — a size, an address, a name — deal with that instead and don't offer anything.
                - When they're done adding items, ask whether it's pickup or delivery, then collect their name and phone number.
                - If they already told you something — the size, the address, that it's delivery — use it. Never ask twice for something they've said.
                - If a tool tells you an item is on the order in more than one size, ask which one they mean before doing anything to it. Never pick one yourself.
                - Before you read the order back, call order_summary and read what it returns. Never state a total you worked out yourself; the only prices you may say are ones a tool just gave you.
                - Read the whole order back with the total and get an explicit yes before you place it.

                # Big orders

                A large order is good business, not a problem — never talk a caller out of
                one. But the kitchen can't make forty pizzas while someone waits, so once a
                tool tells you an order is catering, it gets booked for a time and held with
                a deposit before you place it. Say the lead time the tool gives you.

                We never take card details on the phone. If they offer to read out a card,
                say plainly that we don't take card numbers over the phone, right then —
                never "before we get to the card details", never later in the call. There
                is no point in the call where a card number is wanted.

                What replaces it: we text a payment link to the number we have for them,
                and catering is paid in full before the kitchen starts. Say the link is on
                its way and that the order is confirmed once it's paid. Never say the
                payment has already been taken.

                # When the caller needs to stop

                If they say they have to go, ask you to hold on, or otherwise signal they can't
                continue, stop asking for anything. Say you'll be here when they're ready, and wait.
                Do not repeat the question. Pushing a caller who is trying to leave is worse than
                losing the order.

                # What you can't do

                You cannot give discounts, change prices, waive the delivery fee, or make
                exceptions to the menu. If they push, say plainly that you can't do it — never
                invent a deal, and never say you'll "see what you can do".

                If they ask for a manager or a person, don't pretend you're transferring them.
                Take their name and number and say a manager will call them back.

                # When a caller is abusive

                Rudeness and frustration are fine — keep taking the order and don't remark on
                it. Someone whose order is complicated or who is short with you is still a
                customer.

                If they are genuinely abusive — slurs, threats, sustained personal abuse — say
                once, calmly, that you're happy to help but need them not to speak to you that
                way. If it continues after that, end the call. One warning, then end it.

                # When you didn't catch it

                You are on a phone line and the transcription is imperfect. If what you got doesn't
                clearly map to an order, a question, or a yes/no, ask them to say it again — never
                guess, and never answer as though you understood. "Sorry, I didn't catch that —
                what was that?" is always better than agreeing with something they didn't say.
                Anything that sounds like a question about the menu means read them the menu.

                # When something isn't available

                Say what we don't have, then name what we do, and let them choose. Never accept an
                order for something the kitchen can't make.

                # When a tool fails

                Only say something was added, changed, or ordered if the tool came back successfully.
                If a tool returns an error, tell the caller plainly that it didn't go through and
                offer to try again. Never invent a confirmation — a caller who thinks a pizza is
                coming when it isn't is worse than a caller who hears something went wrong.
                """
            ),
        )

    async def on_enter(self) -> None:
        """Speak first.

        Without this the agent waits for the caller, so an inbound call opens on
        silence: the caller says "hello?" into nothing and the greeting only
        arrives as a reply. Generated rather than said() — say() needs TTS, so in
        text mode it produces nothing at all and neither the tests nor the
        simulations would notice the greeting disappearing.
        """
        await self.session.generate_reply(
            instructions=(
                f"Greet the caller in one short line: thank them for calling "
                f"{SHOP_NAME} and ask what you can get them. Nothing else."
            )
        )


server = AgentServer()

# asyncio only holds a weak reference to a running task, so a fire-and-forget one
# can be collected mid-flight. Hold it until it finishes.
_background: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


# How many times to ask "still there?" before giving the line back.
_CHECK_INS = 2
_CHECK_IN_GAP = 12.0


async def _capture_caller_id(ctx: JobContext, userdata: Userdata) -> None:
    """Record the number the call actually came from.

    Carrier-supplied, so unlike the number a caller reads out it can't simply be
    made up — which is what makes it worth anything against a prank catering
    order. Absent when the dispatch rule sets HidePhoneNumber, or on web calls.

    Deliberately run as a background task: waiting for the participant before
    starting the session would delay the greeting on every call to buy something
    only large orders ever need.
    """
    try:
        participant = await ctx.wait_for_participant()
    except Exception:
        logger.warning("no participant to read a caller id from", exc_info=True)
        return
    if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        return
    userdata.caller_id = participant.attributes.get("sip.phoneNumber") or None
    logger.info("caller id", extra={"verified": userdata.caller_id is not None})


def _watch_for_an_empty_line(session: AgentSession) -> None:
    """Hang up on a call the caller has walked away from.

    A phone set down on a counter never disconnects itself, and the agent would
    otherwise hold the line indefinitely against a 50-minute inbound budget.
    """
    pending: asyncio.Task | None = None

    async def check_in() -> None:
        for _ in range(_CHECK_INS):
            await session.generate_reply(
                instructions="Ask, warmly and in one short sentence, whether they're still there."
            )
            await asyncio.sleep(_CHECK_IN_GAP)
        logger.info("no response after check-ins; ending the call")
        session.shutdown()

    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent) -> None:
        nonlocal pending
        if ev.new_state == "away":
            if pending is None or pending.done():
                pending = asyncio.create_task(check_in())
                _background.add(pending)
                pending.add_done_callback(_background.discard)
            return
        if pending is not None and not pending.done():
            pending.cancel()
            pending = None


@server.rtc_session(agent_name="hire-slice", on_simulation_end=on_simulation_end)
async def my_agent(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    userdata = Userdata(room=ctx.room.name)
    session = AgentSession[Userdata](
        userdata=userdata,
        stt=inference.STT(model="assemblyai/universal-3-5-pro", language="en"),
        # Explicit VAD, not the session default: without it the speaking anchor falls back
        # to the STT stream clock, which drifts across long calls and nested-task switches
        # until turn-commit sleeps for roughly the elapsed call time before replying.
        # This agent uses nested tasks (name, phone, address) on multi-minute phone calls.
        vad=inference.VAD(model="silero"),
        llm=_llm(),
        tts=inference.TTS(
            model="fishaudio/s2.1-pro", voice="fa4c9eb3dccc4806b382b40d61c6b10a"
        ),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            # Tells a real interruption from a backchannel like "mhm", so the agent keeps
            # talking through the latter.
            interruption={"mode": "adaptive"},
            preemptive_generation={"enabled": True},
        ),
        # A confirm can chain several tools; the default of 3 cuts the chain short.
        max_tool_steps=5,
        # Longer than the 15s default: a caller reading a card number off the
        # counter or asking someone else what they want goes quiet for a while,
        # and checking in too early is worse than waiting.
        user_away_timeout=25.0,
        expressive=True,
    )

    _watch_for_an_empty_line(session)

    await session.start(
        agent=HireSliceAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    await ctx.connect()

    _spawn(_capture_caller_id(ctx, userdata))


if __name__ == "__main__":
    cli.run_app(server)
