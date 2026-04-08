# System Tools

CLI tools available on this machine via `run_command`. Use these instead of guessing.

## File operations
- `fd <pattern>` — find files by name (fast, respects .gitignore)
- `tree <dir> -L <depth>` — show directory structure
- `bat <file>` — read file with syntax highlighting and line numbers
- `cat <file>` — read file contents (plain)
- `wc -l <file>` — count lines

## Search
- `rg <pattern>` — search file contents (ripgrep, fast, recursive by default)
- `rg <pattern> --type py` — search only Python files
- `grep -r <pattern> <dir>` — fallback search if rg unavailable

## JSON
- `jq '.<field>' <file>` — parse and filter JSON
- `jq '.' <file>` — pretty-print JSON

## HTTP (requires domain whitelist approval)
- `http GET <url>` — httpie, clean HTTP requests
- `http POST <url> key=value` — POST with JSON body

## Python
- `python3 -c '<code>'` — run inline Python (prefer execute_code tool instead)

## Git
- `git log --oneline -10` — recent commits
- `git diff` — unstaged changes
- `git diff HEAD~1` — last commit diff
- `git status` — working tree status

## Platform
- macOS (ARM/Apple Silicon)
- Shell: zsh
