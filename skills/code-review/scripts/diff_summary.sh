#!/bin/bash
# Generate a summary of recent git changes
echo "=== Recent Commits ==="
git log --oneline -10 2>/dev/null || echo "Not a git repository"
echo ""
echo "=== Files Changed ==="
git diff --stat HEAD~1 2>/dev/null || git diff --stat 2>/dev/null || echo "No changes"
echo ""
echo "=== Diff Summary ==="
git diff --shortstat HEAD~1 2>/dev/null || git diff --shortstat 2>/dev/null || echo "No diff available"
