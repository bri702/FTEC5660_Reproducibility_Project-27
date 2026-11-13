Project 27 Reproduction Results for Three Matching Variants

Each variant runs the same 26 evaluation cases and one documented example.
The aggregate metrics cover the 26 evaluation cases. All three variants use
cases.json from the repository root.

metrics.csv contains the aggregate metrics. case_results.csv contains 81 data
rows across the three variants. raw_mcp.json contains the original MCP responses.

The patches record the two changes in order. 01_original_to_word_boundary.diff
introduces strict whole-word matching. 02_word_boundary_to_plural.diff keeps the
word boundaries and tries a regular plural when the exact keyword has no match.

To reproduce the experiment, install the dependencies and run this command
from the repository root.

    ./.venv/bin/python -B runs/verified-26-three-variants/run_three_variants.py --project . --out local-results/three-variant-26
