# Part 1: Reading and Exploration

**Sources:** Ksenia Se, "What Is MCP, and Why Is Everyone – Suddenly! – Talking About It?" (Hugging
Face blog, March 2025; full version on Turing Post), and the reference
[Fetch MCP server](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch).

The article starts from a simple problem: LLMs are smart but stuck with what they saw in training,
and every time we want one to reach a new data source we end up writing another custom integration.
MCP, which Anthropic released in November 2024, is pitched as the fix. It is one open protocol for
how a model discovers and uses outside tools and data, which turns the N×M problem (every app wired to
every service) into N+M. What I found most useful was the comparison section. Unlike a plain API, an
MCP server describes itself, so the agent can discover its tools at runtime. Unlike ChatGPT plugins,
it is open and not tied to one vendor. And it does not replace frameworks like LangChain: the
orchestration layer still decides *when* to call a tool, while MCP standardises *how*. The article is
also honest about the limits, especially that adding more tools does not mean the model uses them well
if their descriptions are poor, plus security and auth that were still immature.

The architecture has three roles. The **host** is the application the user talks to (Claude Desktop,
an IDE, or in my case `agent.py`). Inside it, the host creates one **client** per server, and each
client keeps a one-to-one session with its server, exchanging JSON-RPC messages over stdio or HTTP. The
**server** exposes capabilities: tools the model can call, resources it can read, and prompt templates.
So the host owns the conversation and the model, and servers only provide capabilities through the
clients.

For the exploration I read the Fetch server. It exposes a single `fetch` tool (plus a matching
prompt), and by the standards from class it is a good example. The interface is well defined: `url`,
`max_length`, `start_index` and `raw` are strictly typed with bounds, and the tool carries annotations
saying it is read-only and idempotent. Failures are predictable, since robots.txt refusals, HTTP errors
and blocked private IPs all come back as clear error results. Long pages are chunked with `start_index`
instead of flooding the context. My main criticism is that it does two jobs, fetching *and* converting
HTML to Markdown, with `raw` switching between them. That is a pragmatic choice, but it fails the "and"
test. The optional Node.js extractor also has no timeout, which makes behaviour less predictable than
the rest of the design.
