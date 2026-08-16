# AGENTS.md

This is a LiveKit Agents project. LiveKit Agents is a Python SDK for building voice AI agents. This project is intended to be used with LiveKit Cloud. See @README.md for more about the rest of the LiveKit ecosystem.

**This project is "Lucky Slice"** — a voice agent that takes pizza takeout and delivery orders, reachable over inbound phone and a web frontend. See the "Lucky Slice specifics" section at the bottom for what is particular to this project.

The following is a guide for working with this project.

## Project structure

This Python project uses the `uv` package manager. You should always use `uv` to install dependencies, run the agent, and run tests.

All app-level code is in the `src/` directory. In general, simple agents can be constructed with a single `agent.py` file. Additional files can be added, but you must retain `agent.py` as the entrypoint (see the associated Dockerfile for how this is deployed).

Be sure to maintain code formatting. You can use the ruff formatter/linter as needed: `uv run ruff format` and `uv run ruff check`.

## LiveKit Documentation

LiveKit Agents is a fast-evolving project, and the documentation is updated frequently. You should always refer to the latest documentation when working with this project. For your convenience, LiveKit offers both a CLI and an MCP server that can be used to browse and search its documentation. If the developer has not yet installed the CLI, you should recommend that they install it.

### LiveKit CLI

The [LiveKit CLI](https://docs.livekit.io/intro/basics/cli/) `lk docs` subcommand gives full access to LiveKit documentation from the terminal. Requires CLI version 2.15.0+. Check with `lk --version`.

Install or update the CLI:

- **macOS:** `brew install livekit-cli` (update: `brew update && brew upgrade livekit-cli`)
- **Linux:** `curl -sSL https://get.livekit.io/cli | bash`
- **Windows:** `winget install LiveKit.LiveKitCLI` (update: `winget upgrade LiveKit.LiveKitCLI`)

LiveKit is a fast-evolving project. Always refer to the latest documentation. Run `lk docs --help` to see available commands. Key commands: `lk docs overview`, `lk docs search`, `lk docs get-page`, `lk docs code-search`, `lk docs changelog`, `lk docs pricing-info`. Run `lk docs <command> --help` before using a command for the first time. Prefer browsing (`overview`, `get-page`) over search, and `search` over `code-search`, as docs pages provide better context than raw code.

Also available on CLI 2.18.2: `lk docs list-sdks` and `lk docs submit-feedback`. Never write a LiveKit API call from memory — pull the current page first.

### LiveKit Docs MCP Server

For deeper IDE integration, LiveKit also offers an [MCP server](https://docs.livekit.io/reference/developer-tools/docs-mcp/) with the same documentation access. It uses Streamable HTTP transport at `https://docs.livekit.io/mcp`. Refer to your IDE's documentation for how to add it.

### Submit docs feedback to LiveKit

If you use the LiveKit CLI or MCP Server to search or browse documentation, also submit constructive feedback to LiveKit with `lk docs submit-feedback` or the MCP `submit_docs_feedback` tool. Add this to your to-do list when planning work, to ensure you file feedback after completing your other tasks. Useful feedback includes incomplete documentation, broken examples, missing steps or any other documentation gap or issue.

## Handoffs and tasks ("workflows")

Voice AI agents are highly sensitive to excessive latency. For this reason, it's important to design complex agents in a structured manner that minimizes the amount of irrelevant context and unnecessary tools included in requests to the LLM. LiveKit Agents supports handoffs (one agent hands control to another) and tasks (tightly-scoped prompts to achieve a specific outcome) to support building reliable workflows. You should make use of these features, instead of writing long instruction prompts that cover multiple phases of a conversation.  Refer to the [documentation](https://docs.livekit.io/agents/build/workflows/) for more information.

## Testing

When possible, add tests for agent behavior. Read the [documentation](https://docs.livekit.io/agents/start/testing/), and refer to existing tests in the `tests/` directory.  Run tests with `uv run pytest`.

Important: When modifying core agent behavior such as instructions, tool descriptions, and tasks/workflows/handoffs, never just guess what will work. Always use test-driven development (TDD) and begin by writing tests for the desired behavior. For instance, if you're planning to add a new tool, write one or more tests for the tool's behavior, then iterate on the tool until the tests pass correctly. This will ensure you are able to produce a working, reliable agent for the user.

## LiveKit CLI

Beyond documentation access, the LiveKit CLI (`lk`) supports other tasks such as managing SIP trunks for telephony-based agents. Run `lk --help` to explore available commands. Inbound phone numbers are managed with `lk number` (`search`, `purchase`, `list`, `get`, `update`).

---

## Lucky Slice specifics

### Model pin — do not "upgrade" without checking

The LLM is pinned to `claude-sonnet-4-6` via `livekit-plugins-anthropic`. That plugin declares:

```python
_NO_PREFILL_PATTERNS = ("claude-sonnet-4-6", "claude-opus-4-6")
```

and suppresses the trailing assistant-turn prefill only for models matching that tuple. Claude 4.6-and-later models reject prefills with a 400, so a newer model id (`claude-opus-5`, `claude-sonnet-5`) falls through, sends a prefill, and fails at runtime — verified against the installed 1.6.10 plugin, not just the docs. Before changing the model, check the tuple in the installed package:

```bash
uv run python -c "from livekit.plugins.anthropic import llm; print(llm._NO_PREFILL_PATTERNS)"
```

`livekit-agents` is pinned to `==1.6.10` rather than a floating `>=`, so the API cannot shift underneath the project between now and a demo.

### Dependencies and secrets

`uv.lock` **is** committed — the Dockerfile does `COPY pyproject.toml uv.lock ./` and the cloud build fails at that line without it. `ANTHROPIC_API_KEY` goes in `.env.local` locally and via `lk agent update-secrets` in the cloud; LiveKit Cloud injects `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` automatically, so do not set those as agent secrets. Never write an empty value into a secrets file — that is a known twirp failure.

### Session stack — deliberate choices

- **`vad=inference.VAD(model="silero")` is explicit and mandatory.** Without it, nested `AgentTask` sessions hit a turn-commit clock-drift bug. This project uses nested tasks (name, phone, address capture), so removing the explicit VAD breaks turn handling in ways that are hard to diagnose.
- Name, phone, and delivery address use the built-in `livekit.agents.beta.workflows` tasks (`GetNameTask`, `GetPhoneNumberTask`, `GetAddressTask`) rather than hand-rolled prompting.
- Every mutating tool returns a **status directive** — e.g. `"… | next: ask if they'd like anything else"` — which keeps a tool-heavy voice flow deterministic.

### Code style

Comments only where the code cannot speak: a constraint, an invariant, or a footgun the code cannot express. No diff narration, no restating a self-describing name, no tutorial prose. When replacing template code, strip its onboarding comments rather than leaving them alongside new logic.

### SDLC

Branch → PR → CI green → squash-merge. `main` holds only merged, CI-passing work. The `ruff` and `tests` GitHub workflows are the gate; PR descriptions say what changed and why.
