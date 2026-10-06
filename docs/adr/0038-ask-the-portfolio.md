# ADR 0038: Questions to the agent are answered by the same read-only loop, behind a code gate

Status: accepted (2026-10-06). Covers FR-AG-08 and FR-DB-09.

## Context
The owner wants to ask the portfolio a question, or have a position analysed, and to see what the answer rests on. An LLM answering free-form is exactly where an invented number could slip through, which the recommendation gate (ADR 0030) exists to prevent.

## Decision
- A question is an agent run of its own type (`ask`, or `analyse_position` when it is about one instrument), using the same context pack, the same 13 read-only tools, privacy mode and budget guard as a review (so it counts toward the monthly budget and the daily run cap). It has two prompts of its own (`ask_investigate.md`, `ask_answer.md`, version 1) and the shared system prompt, and it does two calls as reviews do: the tool loop, then a separate call with structured output (`ANSWER_SCHEMA`: the answer, citations naming tools, and what could not be found).
- The answer passes a pure code gate (`folio/agent/answers.py`) before it is shown: every amount, quantity, weight or percentage written in it must be a number returned by a tool in this run (the same check as for recommendations, so in privacy mode a euro amount can never pass), and every citation must name a tool the run called (`web_search` only if it returned pages). An answer that fails is kept in the run's trace (with the model's raw text) but is not shown as an answer; the page says it did not pass and why.
- The rows the answer rests on are shown: for each cited tool, the first call to it with its input and its (shortened) result, taken from the run's recorded tool calls.
- It only reads. No recommendation, no calculation, no draft transaction and no inbox item is made, and the tool set has no write tool. The text is labelled AI-generated and not financial advice, and the prompt tells the model to describe what the data and the owner's principles show without telling the owner to buy or sell.
- It is asynchronous like "Run a review now": `POST /agent/ask` makes the run row (status `queued`) and queues a job; the worker answers; the page polls `GET /agent/ask/{id}` every three seconds until the status leaves queued and running. A run still queued when no worker has picked it up shows the working note; a question put with the agent off or no key is refused at once with 409.
- The same panel is used on Insights, on the position page and in the `ask` dashboard widget (option: how many earlier answers to keep).

## Consequences
The number check is global to the run (a number in any tool result counts), so an answer could attach a real number to the wrong thing; the data panel is what lets the owner see that. A question costs about as much as a small review (a few cents). The check can refuse a correct answer that rounds a number or adds two together, which the prompt forbids; refusing is the safe side.
