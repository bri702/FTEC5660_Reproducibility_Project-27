# Project No.27 Reproducing MCP Retrieval in Codified Context

Project 27 reproduces local context retrieval in Codified Context. The Model Context Protocol (MCP) server reads a game development task, scores codebase subsystems by keyword matches, and recommends relevant subsystems and file paths. The experiment compares three matching rules on the same 26 evaluation cases. [Paper §3.3.1](https://arxiv.org/html/2602.20478v1#S3.SS3.SSS1) · [Author's MCP documentation](https://github.com/arisvas4/codified-context-infrastructure/tree/6b0408fe86d8e802bcbd00cd6d2d057f288f518a/mcp-server)

Codified Context organizes project knowledge into three layers: project rules, specialist agents, and documentation retrieved on demand. This reproduction focuses on the third layer's `find_relevant_context` tool. [Three-layer architecture](https://arxiv.org/html/2602.20478v1#S3)

## Experimental Variants

All three variants use the same queries in the same order. The case file contains 26 custom evaluation cases and one example from the author's documentation. Each evaluation case has a label identifying the subsystem to investigate first. The variants share the subsystem index, scoring weights, ranking rules, and file recommendation rules. [Case file](cases.json)

1. **Original substring matching.** The baseline uses version 1.0.0 of the author's MCP server. A keyword can match within another word, as when `screen` inside `screenshot` scores a point for `aiming`. For the documented query `fix camera offset`, the baseline ranks `rendering` first and includes `coordinate-systems.md` among the suggested paths. The results record this example separately and calculate the aggregate metrics on the 26 evaluation cases. [Author's example](https://github.com/arisvas4/codified-context-infrastructure/blob/v1.0.0/mcp-server/README.md#key-data-structures)
2. **Strict whole-word matching.** The first change requires word boundaries around a keyword, which removes the match for `screen` inside `screenshot`. It also misses regular plurals. The query `Sprites and textures flicker.` returns an empty list. [First patch](runs/verified-26-three-variants/01_original_to_word_boundary.diff)
3. **Whole-word matching with regular plurals.** The second change checks the full keyword first. If there is no match, it tries the regular plural of the keyword's final word. This lets `sprites` and `textures` match `sprite` and `texture`, respectively. The word boundary still excludes `text` inside `textures`, and `rendering` ranks first again. [Second patch](runs/verified-26-three-variants/02_word_boundary_to_plural.diff)

## Setup and Reproduction

You need Python 3.12 and Git. Run these commands in a system terminal or in PyCharm's **Terminal**.

```bash
git clone https://github.com/bri702/FTEC5660_Reproducibility_Project-27.git
cd FTEC5660_Reproducibility_Project-27
python3.12 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -B runs/verified-26-three-variants/run_three_variants.py --project . --out local-results/three-variant-26
```

Once the dependencies are installed, run the last command from the repository root. It writes results to `local-results/three-variant-26/`. For each rerun, set `--out` to a directory that does not already exist. The script creates temporary versions of the modified server and runs all three MCP servers locally in sequence. After installation, the experiment runs offline without a model or an API key. [Reproduction script](runs/verified-26-three-variants/run_three_variants.py)

## Results on 26 Evaluation Cases

| Variant | Top-1 hits | Top-3 hits | Unlabeled candidates in the top three |
| --- | ---: | ---: | ---: |
| Original substring matching | 21/26 (80.8%) | 25/26 (96.2%) | 42 |
| Strict whole-word matching | 18/26 (69.2%) | 21/26 (80.8%) | 20 |
| Whole-word matching with regular plurals | 23/26 (88.5%) | 26/26 (100%) | 23 |

Top-1 hits count cases where the labeled subsystem ranks first. Top-3 hits count cases where it appears among the first three results. The final column adds up the top-three candidates that differ from the label for each case.

Adding regular plurals recovered five hits at each cutoff compared with strict whole-word matching. Compared with the original version, the final variant gained two Top-1 hits and one Top-3 hit. The number of unlabeled candidates in the top three fell from 42 to 23.

- **Gamepad reconnect.** The original version scores `ai` inside `fails` for the AI subsystem. The final version removes that match, moving `input` from second to first.
- **Music plays twice after loading a save.** The original version matches `save` inside `saved` and `load` inside `loading`. The final version moves `audio` from third to first.
- **Incorrect health bar color.** Excluding `heal` inside `health` moves `ui` from fourth to third. Both the combat and damage subsystems still match the full keyword `health`.
- **A rifle fires two projectiles per trigger press.** The final version still ranks `aiming` first and `combat` second. The `aiming` index contains both `fire` and `projectile` as full keywords.

## Result Files

The `runs/` directory contains one set of verified results for all three variants. To compare the original and final versions, use the `original` and `whole_word_plural` rows in the CSV files.

| File | Contents |
| --- | --- |
| [metrics.csv](runs/verified-26-three-variants/metrics.csv) | Aggregate metrics, one row per variant |
| [case_results.csv](runs/verified-26-three-variants/case_results.csv) | 81 data rows, with 26 evaluation cases and one documented example per variant |
| [raw_mcp.json](runs/verified-26-three-variants/raw_mcp.json) | Raw MCP responses, including subsystem rankings, matched keywords, and recommended files |
| [01_original_to_word_boundary.diff](runs/verified-26-three-variants/01_original_to_word_boundary.diff) | Changes from the original to strict whole-word matching |
| [02_word_boundary_to_plural.diff](runs/verified-26-three-variants/02_word_boundary_to_plural.diff) | Changes from strict whole-word matching to regular plural handling |
| [whole_word_plural.diff](runs/verified-26-three-variants/whole_word_plural.diff) | Direct comparison between the original and final versions, as discussed in the report |

A rerun also writes `run.json` and the server logs for each variant to the specified output directory.

## Scope and Limitations

The results describe MCP retrieval on this set of 26 tasks, including cases designed to expose unintended substring matches. Each task labels one priority subsystem, so other returned subsystems can still help with diagnosis. The paper also examines development sessions and case studies. This experiment measures retrieval, so its metrics do not estimate agent code correctness or development efficiency. [Paper evaluation scope](https://arxiv.org/html/2602.20478v1#S4.SS1)

## Debugging Log

The first change used strict whole-word matching to remove unintended matches within words. To isolate the effect of the matching rule, all three variants ran the same 26 evaluation cases in the same order with the same labels and scoring rules. Strict matching reduced Top-1 hits from 21/26 to 18/26 and Top-3 hits from 25/26 to 21/26.

The strict variant returned an empty list for `render-plurals` (`Sprites and textures flicker.`). The indexed keywords are `sprite` and `texture`. Because each plural ends in `s`, there is no word boundary after the indexed singular form in the query.

The second change kept word boundaries and added regular plural handling for the final word of a keyword. This restored `rendering` to first place for that query and still excluded `text` inside `textures`. On the same 26 cases, Top-1 hits rose to 23/26 and Top-3 hits rose to 26/26, five more hits at each cutoff than strict matching. The count of unlabeled candidates in the top three rose from 20 to 23, compared with 42 for the original version. [Per-case results](runs/verified-26-three-variants/case_results.csv) · [Aggregate metrics](runs/verified-26-three-variants/metrics.csv)

## Source and License

`upstream/server.py` contains the author's version 1.0.0 source at commit `6b0408fe86d8e802bcbd00cd6d2d057f288f518a`. The upstream code is under the MIT license, included with the source. [Pinned upstream source](https://github.com/arisvas4/codified-context-infrastructure/tree/6b0408fe86d8e802bcbd00cd6d2d057f288f518a) · [MIT license](https://github.com/arisvas4/codified-context-infrastructure/blob/6b0408fe86d8e802bcbd00cd6d2d057f288f518a/LICENSE)
