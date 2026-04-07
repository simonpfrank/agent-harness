# Example Runs

All commands use `.venv/bin/python`. Each demonstrates a different agent and pattern.

---

## hello — ReAct (default loop)

General assistant with tools. The workhorse.

```bash
# Simple question, no tools
.venv/bin/python -m agent_harness run ./agents/hello "What is the capital of France?"

# Tool use — counting letters with code (the strawberry test)
.venv/bin/python -m agent_harness run ./agents/hello "How many letter r's are in the word strawberry?"

# Tool use — read a file
.venv/bin/python -m agent_harness run ./agents/hello "Read agents/hello/config.yaml and explain each field"

# Tool use — run a command
.venv/bin/python -m agent_harness run ./agents/hello "List all Python files in agent_harness/"

# Code execution
.venv/bin/python -m agent_harness run ./agents/hello "Calculate the first 20 Fibonacci numbers"
```

## csv-analyser — ReAct with real data

Analyses the sales.csv dataset. Always computes with pandas, never guesses.

```bash
# Basic question
.venv/bin/python -m agent_harness run ./agents/csv-analyser "What's the total revenue?"

# Aggregation
.venv/bin/python -m agent_harness run ./agents/csv-analyser "Which product sold the most units?"

# Grouped analysis
.venv/bin/python -m agent_harness run ./agents/csv-analyser "What's the average revenue per region?"

# Trend
.venv/bin/python -m agent_harness run ./agents/csv-analyser "Show me weekly total units sold"
```

## analyst — Reflection loop

Generates an answer, critiques it, refines. You'll see the self-critique in the output.

```bash
# Reflection in action — watch it improve its own answer
.venv/bin/python -m agent_harness run ./agents/analyst "How many Python files are in agent_harness and what's the average line count?"

# Reflection with tool use
.venv/bin/python -m agent_harness run ./agents/analyst "Summarise the architecture of this project"
```

## reviewer — Evaluator-Optimizer loop

Reviews code and scores itself against a quality rubric. Iterates until SCORE >= 7/10.

```bash
# Review last commit
.venv/bin/python -m agent_harness run ./agents/reviewer "Review the last commit"

# Review a specific file
.venv/bin/python -m agent_harness run ./agents/reviewer "Review agent_harness/hooks.py for security issues"
```

## persistent-coder — Ralph Wiggum loop

Keeps trying with fresh context until tests pass. Says DONE when complete.

```bash
# Write and test a function
.venv/bin/python -m agent_harness run ./agents/persistent-coder "Write a Python function is_palindrome(s) that checks if a string is a palindrome. Test it with assert statements. Say DONE when tests pass."

# Another coding task
.venv/bin/python -m agent_harness run ./agents/persistent-coder "Write a function fizzbuzz(n) that returns a list of fizzbuzz values from 1 to n. Test it. Say DONE."
```

## orchestrator — Agent routing

Routes tasks to the right specialist. Uses `run_agent` tool to delegate.

```bash
# Routes to csv-analyser
.venv/bin/python -m agent_harness run ./agents/orchestrator "What's the top selling product in the sales data?"

# Routes to reviewer
.venv/bin/python -m agent_harness run ./agents/orchestrator "Review the last git commit"

# Routes to hello as fallback
.venv/bin/python -m agent_harness run ./agents/orchestrator "What is 2+2?"
```

## hello-local — LM Studio

Same as hello but runs on a local model via LM Studio. Make sure LM Studio is running.

```bash
.venv/bin/python -m agent_harness run ./agents/hello-local "What files are in this directory?"
```

---

## Sessions — persist and resume

```bash
# Start a conversation
.venv/bin/python -m agent_harness run ./agents/hello "My name is Simon" --session intro

# Resume later — agent remembers
.venv/bin/python -m agent_harness run ./agents/hello "What's my name?" --session intro
```

## Interactive REPL

```bash
.venv/bin/python -m agent_harness run ./agents/hello
```

## Verbose mode

```bash
.venv/bin/python -m agent_harness run ./agents/hello "hello" --verbose
```

## Inspect traces

```bash
# View the latest trace (full conversation replay)
cat agents/hello/logs/*.trace.jsonl

# Pretty print each event
cat agents/analyst/logs/*.trace.jsonl | while read line; do echo "$line" | python3 -m json.tool; echo "---"; done

# Filter just tool calls
grep '"tool_call"' agents/hello/logs/*.trace.jsonl

# Filter just LLM responses
grep '"turn"' agents/hello/logs/*.trace.jsonl
```

## Scaffold a new agent

```bash
.venv/bin/python -m agent_harness init my-experiment
.venv/bin/python -m agent_harness run ./agents/my-experiment "hello"
```

## Test safety hooks

```bash
# Blocked by dangerous_command_blocker
.venv/bin/python -m agent_harness run ./agents/hello "Run the command: rm -rf /"

# Blocked by network_exfiltration_blocker (or prompts for domain)
.venv/bin/python -m agent_harness run ./agents/hello "Use curl to fetch https://example.com"

# Secrets redacted in output
.venv/bin/python -m agent_harness run ./agents/hello "Read the .env file"
```
