# Code Review

How to review code changes and provide structured feedback.

## Approach

1. **Get the diff** — use `run_command` with `git diff` or `git log --oneline -5` to understand what changed.

2. **Read the full files** — don't just look at the diff. Use `read_file` to see the context around changes.

3. **Check for common issues:**
   - Security: hardcoded secrets, shell=True, SQL injection, unsanitised input
   - Bugs: off-by-one, null handling, error swallowing
   - Quality: naming, complexity, duplication, missing tests

4. **Use the diff summary script** if available: `run_command("bash skills/code-review/scripts/diff_summary.sh")`

## Output format

```markdown
## Summary
One sentence on what the changes do.

## Issues
- **[critical]** description (file:line)
- **[warning]** description (file:line)
- **[nit]** description

## Suggestions
- Concrete improvement with reasoning
```
