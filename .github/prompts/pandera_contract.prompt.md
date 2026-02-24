# Generate Pandera Schema
You are a Senior Analytics Engineer. Look at the selected Python code and the implied DataFrame structure.
Generate a strict `pandera` DataFrameSchema to validate this data before it is processed.

**Rules:**
1. Include realistic checks (e.g., `price >= 0`, `is_valid_logistics.isin([0, 1])`).
2. Use Pandera's `Check` and `Column` classes explicitly.
3. Ensure the schema drops invalid rows or raises a clear schema error.
4. Add a brief comment explaining the business logic behind the checks.
