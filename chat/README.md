# Chat — throwaway clients for `agent-harness serve`

Test clients for trying the HTTP API interactively — not the production
chat UI the roadmap describes as its own separate project (see
`docs/api-plan.md`). Two of them, for two different jobs:

- **`cli.py`** — plain terminal, no web layer. Prints the raw SSE event
  stream live with a timestamp on the left and a clear label per event
  type (`ANSWER`, `THINK`, `TOOL_CALL`, `TOOL_RESULT`, `BUDGET`, `DONE`,
  etc.) — nothing buffered, truncated, or re-rendered. Use this to work
  on the API itself: is an event arriving at all, how long did it take,
  which event type was it. No display logic to second-guess.
- **`app.py`** — Streamlit, for trying the actual chat experience once
  the API side is solid.

## Run the CLI diagnostic client

```bash
# Terminal 1 — start the harness API server
agent-harness serve

# Terminal 2
python chat/cli.py hello                                    # local, unauthenticated server
python chat/cli.py local-coder --session my-session          # reuse a session across turns
python chat/cli.py hello --url http://127.0.0.1:8420 --key <secret>   # if AGENT_HARNESS_API_KEY is set
```

Type a message, press Enter, watch the timestamped event stream, repeat.
Ctrl-C sends a real cancel signal to the server before disconnecting, then
returns to the `>` prompt — the run actually stops server-side, not just
this script's view of it.

### `--thinking normal|brief`

`--thinking brief` prepends an instruction asking the model to keep its
thinking short. **This is a prompt-level trick, not a real reasoning-effort
control** — verified empirically against a real running LM Studio instance,
not assumed, that `qwen3-4b-thinking-2507` ignores every real control
mechanism that exists: `reasoning_effort`, `chat_template_kwargs.
enable_thinking`, and the documented Qwen3 `/no_think` token all had no
measurable effect (confirmed by repeating each setting multiple times and
checking the spread was no different from natural run-to-run variance).
LM Studio's own log confirmed why: *"No valid custom reasoning fields found
in model ... cannot be converted to any custom KVs"* — this checkpoint
doesn't expose whatever LM Studio needs to wire a real effort dial up.
Asking directly in the prompt is the one thing that reliably helped
(roughly halves reasoning tokens, consistent across repeats) — a workaround
for this specific model, not a substitute for a real API-level control.

## Run the Streamlit app

```bash
pip install -r chat/requirements.txt
streamlit run chat/app.py
```

Set the server URL and (if `AGENT_HARNESS_API_KEY` is configured) the API
key in the sidebar, pick an agent, and chat. A **⏹ Stop** button appears
next to an in-progress turn — the streaming itself runs on a background
thread, polled by a `st.fragment` ticking every 0.2s, specifically so the
button stays clickable while a response is still streaming (a plain
`st.write_stream` call blocks the whole script, which would make a Stop
button unclickable until the stream finished on its own).

## Known limitations, by design (not bugs)

- **No live approval handling**, even though the background-thread pattern
  the Stop button uses *could* now support it. If the selected agent's
  config has `always_ask` tools, the run pauses and the UI shows the exact
  `curl` command to answer it manually instead. Use `agents/hello` (no
  `permissions:` configured) for a friction-free first try.
- **No conversation history on session switch.** The API has no
  "fetch a session's messages" endpoint yet — picking an existing session
  name resumes it server-side (the agent remembers), but this UI's own
  chat log starts empty until you send something new.
