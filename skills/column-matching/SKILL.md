# Column Matching

How to match columns between two data files (e.g. an incoming file to a reference/template).

## Core Principle

**No false positives.** If in doubt, put the column in `non_matches` with reasoning. A missed match can be added later; a wrong match causes downstream data corruption.

## Matching Signals (in priority order)

1. **Sample values** — strongest signal. Do the actual values match or clearly relate? (e.g. M/F vs Male/Female, POL001 vs P001)
2. **Data type compatibility** — must be compatible. Don't match a date column to a numeric column.
3. **Column name semantics** — consider abbreviations, domain-specific terminology, different naming conventions (snake_case vs camelCase vs spaces).
4. **Data patterns and formats** — ID formats (AAA999), date formats (YYYY-MM-DD vs DD/MM/YYYY), numeric precision.
5. **Population rates** — a fully populated column is unlikely to match a sparse one unless the input is a subset.
6. **Business context** — domain knowledge about what columns represent.

## Multi-Signal Validation

A confident match needs 3+ signals aligning:
- Sample values match or are clearly related
- Data types are compatible
- Semantic meaning is similar
- Patterns align

A match with only 1-2 signals should be flagged as uncertain or placed in `non_matches`.

## Confidence Scoring

| Score | Meaning | When to use |
|-------|---------|-------------|
| 0.95-1.0 | Near certain | Multiple strong signals: values + types + semantics + domain |
| 0.85-0.94 | Strong match | Semantic match with confirming signals |
| 0.70-0.84 | Probable match | Good match but some uncertainty |
| 0.60-0.69 | Weak match | Review recommended, insufficient signals |
| < 0.60 | Do not match | Put in non_matches with reasoning |

Be conservative. Only assign > 0.9 with multiple confirming signals.

## Rules

- **1:1 matching only** — each input column matches at most one reference column
- **Never force a match** — unmatched columns are fine
- **Always explain reasoning** — cite the specific signals that led to the match
- **Profile before matching** — use `profile_data` on both files first to get structured metadata
- **Use memory** — save successful match patterns for future use, recall past matches for consistency

## Output Format

Return a JSON object:

```json
{
  "matches": [
    {
      "input_column": "col_name",
      "reference_column": "ref_name",
      "confidence": 0.95,
      "reasoning": "Sample values align: M/F matches Male/Female. Both categorical text. Semantic: both gender fields."
    }
  ],
  "non_matches": [
    {
      "input_column": "col_name",
      "reasoning": "Why no match was found",
      "possibilities": [
        {
          "reference_column": "ref_name",
          "reason": "Why it almost matched but confidence too low"
        }
      ]
    }
  ],
  "unmatched_input": ["columns", "with", "no", "match"],
  "unmatched_reference": ["reference", "columns", "not", "matched"]
}
```

## Using Memory for Matching

- **After a successful run**: save match patterns (e.g. "pol_id -> PolicyID, pension scheme identifier") so future runs on similar data are faster and more consistent.
- **Before matching**: recall past matches to check if you've seen similar column names or patterns before.
- **Record false positives**: if a match was wrong, save that as a negative example to avoid repeating it.
