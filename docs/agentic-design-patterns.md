# Agentic Design Patterns

Industry-standard patterns for LLM agent architectures. Each pattern describes a different approach to how an agent reasons, plans, acts, and learns.

*Compiled from: Google Cloud Architecture Center, LangChain/LangGraph, IBM, academic surveys (arxiv 2601.12560, 2510.25445), and production frameworks.*

---

## Single-Agent Patterns

### 1. ReAct (Reason + Act)
**Loop:** Think → Act → Observe → repeat until done.

The agent interleaves reasoning ("I should check the file") with tool calls ("read_file foo.txt") and observes results before deciding the next step. The most common pattern — simple, reliable, easy to debug.

**When to use:** General-purpose tasks, exploratory work, tasks where the steps aren't known upfront.

### 2. Plan-and-Execute
**Loop:** Plan all steps upfront → Execute each step → Summarise.

The planning phase produces a numbered plan with no tool access. Each step is then executed (often as a mini ReAct loop). Separates strategy from execution.

**When to use:** Multi-step tasks with predictable structure. Research shows 92% task completion with 3.6x speedup over sequential ReAct.

### 3. ReWOO (Reasoning Without Observation)
**Loop:** Plan with placeholders → Execute all tools in parallel → Solve with results.

Three phases: Planner creates a full blueprint using placeholder variables for tool outputs. Worker executes all tool calls (potentially in parallel). Solver assembles the final answer from all results.

**When to use:** Multi-hop questions where tool calls are independent. Significantly fewer LLM calls than ReAct because the plan is made once, not interleaved.

### 4. Reflection / Self-Refine
**Loop:** Generate → Critique → Refine → repeat until quality threshold met.

The agent produces output, then critiques its own work ("is this correct? what did I miss?"), then refines. Can use the same LLM or a separate evaluator. Reflexion adds memory — storing insights from past attempts.

**When to use:** Writing, code generation, any task where quality improves with iteration. Not useful for simple factual lookups.

### 5. CodeAct
**Loop:** Write code → Execute → Check result → Fix if failed → repeat.

The agent treats code as its primary action medium. Instead of calling predefined tools, it writes and executes code to solve problems. Includes a self-correction loop for failed executions.

**When to use:** Data analysis, computation, tasks where the answer is best obtained by running code. Our `execute_code` tool enables this pattern within ReAct.

### 6. Tree-of-Thoughts (ToT)
**Loop:** Generate multiple candidate thoughts → Evaluate each → Expand best → repeat.

Extends chain-of-thought by exploring multiple reasoning paths simultaneously. The agent branches out, evaluates partial solutions, and prunes bad paths. Requires multiple LLM calls per step.

**When to use:** Complex reasoning problems (puzzles, math, strategic planning). Expensive — many LLM calls. Not practical for routine tasks.

### 7. LATS (Language Agent Tree Search)
**Loop:** Build decision tree → Evaluate states → Select best action → Self-reflect → repeat.

Combines tree search with self-reflection. Each state is a node, each action is an edge. Uses Monte Carlo Tree Search (MCTS) principles. The agent evaluates which branch to explore next.

**When to use:** Tasks requiring exploration of multiple strategies. Research and complex problem-solving. Very expensive in LLM calls.

### 8. Ralph Wiggum Loop (Naive Persistence)
**Loop:** Run agent → Check if task complete → If not, discard context and retry fresh → repeat until done or max attempts.

Instead of sophisticated error recovery, throw away the failed attempt and start clean. LLMs degrade over long contexts — a fresh start often outperforms accumulated confusion. Named after the Simpsons character; the philosophy is "the agent *will* fail, and that's fine."

**When to use:** Coding tasks with testable completion criteria (tests pass, linter clean). Any task where you can programmatically verify "done". Popularised by Geoffrey Huntley in late 2025.

---

## Multi-Agent Patterns

### 8. Orchestrator-Worker
**Pattern:** Orchestrator receives task → Decomposes into subtasks → Delegates to specialist workers → Synthesises results.

The orchestrator maintains context and coordinates. Workers are stateless specialists. Can run workers in parallel for independent subtasks.

**When to use:** Complex tasks requiring different expertise (research + analysis + writing). The orchestrator's instructions.md defines routing logic.

### 9. Evaluator-Optimizer
**Pattern:** Generator produces output → Evaluator scores it → Optimizer adjusts approach → repeat.

Separates the "doer" from the "judge". The evaluator uses rubrics or an LLM-as-judge approach. The optimizer adjusts strategy based on evaluation feedback.

**When to use:** Content generation requiring quality standards. Code review. Any task with measurable quality criteria.

### 10. Handoff / Relay
**Pattern:** Active agent changes dynamically based on conversation context. Each agent can transfer to another via tool call.

No central orchestrator. Agents decide when to hand off based on their own assessment. State passes between agents.

**When to use:** Customer service flows, multi-domain conversations where expertise changes mid-task.

### 11. Debate / Adversarial
**Pattern:** Two or more agents argue opposing positions → Synthesiser reconciles into final answer.

Improves reasoning by forcing agents to defend positions. The debate creates a richer exploration of the problem space than single-agent reasoning.

**When to use:** Decision-making, risk assessment, any task where considering counterarguments improves quality.

### 12. Pipeline / Sequential
**Pattern:** Agent A → Agent B → Agent C. Each agent processes and passes to the next.

Simple linear chain. Each agent adds value and passes forward. No feedback loops.

**When to use:** Well-defined workflows (extract → transform → load, draft → edit → format).

### 13. Mixture of Experts (MoE)
**Pattern:** Router examines input → Selects which expert agent(s) to activate → Combines their outputs.

Only the relevant experts run for each input. Different from orchestrator-worker because the router is lightweight (often rule-based) and experts are full agents.

**When to use:** Tasks with clearly distinct domains (legal vs technical vs financial). Reduces cost by only activating relevant experts.

### 14. Parallelization (Fan-out / Fan-in)
**Pattern:** Orchestrator splits task into independent subtasks → runs all concurrently → merges results.

Different from orchestrator-worker where subtasks run sequentially. Here, independent subtasks execute simultaneously. A research task might search 5 sources in parallel then synthesise.

**When to use:** Tasks with independent subtasks (searching multiple sources, processing multiple files). Requires async execution.

### 15. Agentic RAG
**Pattern:** Agent decides when to retrieve → searches knowledge base → evaluates relevance → re-queries if needed → generates answer grounded in retrieved context.

Not just "search then answer" — the agent iteratively retrieves, evaluates, and refines queries until it has enough information. Combines ReAct with retrieval tools.

**When to use:** Question answering over large document collections, fact-checking, research tasks where the agent needs to find and verify information.

### 16. Deep Research
**Pattern:** Search → Extract key information → Identify knowledge gaps → Follow-up searches → Synthesise comprehensive report.

Multi-phase research with reflection between phases. The agent builds understanding iteratively, identifying what it doesn't know and searching specifically for that. Often produces a structured report with citations.

**When to use:** Comprehensive research tasks, literature reviews, competitive analysis. Can be approximated with Plan-and-Execute + reflection.

### 17. Consensus / Voting
**Pattern:** Multiple agents independently solve the same problem → Compare results → Take majority answer or synthesise agreement.

Improves reliability by getting multiple independent perspectives. If 3 out of 4 agents agree, confidence is high. Different from debate (where agents see each other's work) — here they work independently.

**When to use:** High-stakes decisions, fact verification, any task where independent agreement increases confidence. Expensive (N times the LLM calls).

---

## Meta-Patterns (implemented as framework features, not loops)

### Guardrails
Deterministic safety checks before and after tool execution. Not an agent pattern per se — it's infrastructure that wraps any pattern. Our hooks system implements this.

### Human-in-the-Loop
User approval gates at key decision points. Our permissions system implements this. Can be combined with any pattern above.

---

## Sources

- [Google Cloud: Choose a design pattern for agentic AI](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system)
- [Agentic AI Design Patterns: ReAct, ReWOO, CodeAct, and Beyond](https://capabl.in/blog/agentic-ai-design-patterns-react-rewoo-codeact-and-beyond)
- [Arxiv: Architectures, Taxonomies, and Evaluation of LLM Agents](https://arxiv.org/html/2601.12560v1)
- [LangChain: Choosing the Right Multi-Agent Architecture](https://blog.langchain.com/choosing-the-right-multi-agent-architecture/)
- [7 Must-Know Agentic AI Design Patterns](https://machinelearningmastery.com/7-must-know-agentic-ai-design-patterns/)
- [Redis: AI Agent Architecture Patterns](https://redis.io/blog/ai-agent-architecture-patterns/)
- [Navigating Modern LLM Agent Architectures](https://www.wollenlabs.com/blog-posts/navigating-modern-llm-agent-architectures-multi-agents-plan-and-execute-rewoo-tree-of-thoughts-and-react)
- [Ralph Wiggum Loop — HumanLayer](https://www.humanlayer.dev/blog/brief-history-of-ralph)
