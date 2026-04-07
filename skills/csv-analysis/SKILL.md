# CSV Analysis

How to analyse CSV data deterministically using tools.

## Approach

1. **Examine structure first** — use `read_file` to read the first 5-10 lines. Identify columns, data types, and delimiters.

2. **Write code, don't guess** — always use `execute_code` with pandas for numerical answers. Never estimate or count manually.

3. **Validate results** — check row counts, null values, and data types before drawing conclusions.

## Template

```python
import pandas as pd

df = pd.read_csv('path/to/file.csv')
print(f"Shape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(df.describe())
```

## Common pitfalls

- CSV files may have different encodings — try `encoding='utf-8'` first, then `'latin-1'`
- Large files: use `nrows=1000` for initial exploration
- Mixed types in columns: pandas may infer wrong dtype, check with `df.dtypes`
