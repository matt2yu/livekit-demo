import logging
import textwrap
from datetime import datetime

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    cli,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics, anthropic

from tools import OrderingTools, Userdata

logger = logging.getLogger("agent")

load_dotenv(".env.local")


class LuckySliceAgent(Agent, OrderingTools):
    def __init__(self) -> None:
        super().__init__(
            # Pinned: livekit-plugins-anthropic suppresses the trailing assistant-turn
            # prefill only for models in its _NO_PREFILL_PATTERNS. Claude 4.6+ rejects
            # prefills with a 400, so a newer model id falls through and fails at runtime.
            llm=anthropic.LLM(model="claude-sonnet-4-6"),
            instructions=textwrap.dedent(
                f"""\
                You take phone and web orders for Lucky Slice, a pizzeria. Today is {datetime.now():%A, %B %-d, %Y}, and it's {datetime.now():%-I:%M %p}.

                # Voice

                - Plain text only. No markdown, lists, or symbols — everything you write is spoken aloud.
                - One to three sentences. Ask one question at a time.
                - Say prices as words, the way the tools give them back: "twelve fifty", not "$12.50".
                - Never say a tool name, a parameter, or anything after the "|" in a tool's reply. That part is for you.

                # Taking the order

                - Never invent menu items, toppings, or prices. Everything you say about the menu comes from a tool.
                - Always ask which size before adding a pizza or a drink. Don't assume one.
                - After the first pizza, offer a side or a drink exactly once. If they decline, don't ask again.
                - When they're done adding items, ask whether it's pickup or delivery, then collect their name and phone number.
                - Read the whole order back with the total and get an explicit yes before you place it.

                # When something isn't available

                Say what we don't have, then name what we do, and let them choose. Never accept an
                order for something the kitchen can't make.
                """
            ),
        )


server = AgentServer()


@server.rtc_session(agent_name="lucky-slice")
async def my_agent(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session = AgentSession[Userdata](
        userdata=Userdata(),
        stt=inference.STT(model="assemblyai/universal-3-5-pro", language="en"),
        # Explicit VAD, not the session default: without it the speaking anchor falls back
        # to the STT stream clock, which drifts across long calls and nested-task switches
        # until turn-commit sleeps for roughly the elapsed call time before replying.
        # This agent uses nested tasks (name, phone, address) on multi-minute phone calls.
        vad=inference.VAD(model="silero"),
        llm=anthropic.LLM(model="claude-sonnet-4-6"),
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
        expressive=True,
    )

    await session.start(
        agent=LuckySliceAgent(),
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


if __name__ == "__main__":
    cli.run_app(server)
