Browser tools (`browser_navigate`, `browser_click`, `browser_snapshot`,
`browser_wait_for`, `browser_tabs`, `browser_close`) come from the
`playwright` MCP server, not this harness — they let you see and interact
with a real, live browser page.

`browser_snapshot` shows you the page's interactive elements (links,
buttons, fields) by role and name, not the full page text — use it to see
what you can click or navigate to, before deciding what to do next.

Use `read_live_page_content` only when you actually want to read a page's
content (e.g. a news article) — it extracts the readable text of whatever
page is currently open. Don't call it just to navigate; that wastes tokens
on content you don't need yet.

Navigating to a new domain — including by clicking a link that leads
somewhere new — may pause for the user's approval. If a navigation comes
back saying it "was not approved and has been reverted," that's expected
behavior, not an error: report it to the user rather than retrying.
