"""Compare the published Codified Context MCP search with whole-word matching and regular plurals."""
import argparse
import asyncio
import csv
import difflib
import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent
AUTHOR_REPO = "https://github.com/arisvas4/codified-context-infrastructure"
AUTHOR_COMMIT = "6b0408fe86d8e802bcbd00cd6d2d057f288f518a"
SERVER = ROOT / "upstream" / "server.py"
SUBSTRING_MATCH = "            if keyword in task_lower:"
PLURAL_MATCH = "            if _whole_word_with_plural(keyword, task_lower):"
RETRIEVAL_TOOL = "@mcp.tool()\ndef find_relevant_context("
PLURAL_MATCHER = r'''
def _whole_word_with_plural(keyword: str, task: str) -> bool:
    def whole_word(candidate: str) -> bool:
        return bool(re.search(r"(?<!\w)" + re.escape(candidate) + r"(?!\w)", task))

    if whole_word(keyword):
        return True

    # Inflect the last word of a keyword phrase. Keep short terms such as AI exact.
    last_word = re.search(r"(?<![a-z])[a-z]{3,}$", keyword)
    if last_word is None:
        return False
    word = last_word.group()
    if word.endswith(("s", "x", "z", "ch", "sh")):
        plural = word + "es"
    elif word.endswith("y") and word[-2] not in "aeiou":
        plural = word[:-1] + "ies"
    else:
        plural = word + "s"
    return whole_word(keyword[:last_word.start()] + plural)
'''


@dataclass(frozen=True)
class Case:
    group: str
    id: str
    query: str
    expected_subsystems: tuple[str, ...]
    notes: str
    source: str | None


def load_cases(path: Path) -> list[Case]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        Case(group, item["id"], item["query"], tuple(item["expected_subsystems"]),
             item["notes"], item.get("source"))
        for group in ("documented_examples", "evaluation")
        for item in data[group]
    ]
    if not all(case.id.strip() and case.query.strip() for case in cases):
        raise ValueError("Every case needs a nonempty ID and query.")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Case IDs must be unique.")
    evaluation = [case for case in cases if case.group == "evaluation"]
    if not any(case.expected_subsystems for case in evaluation):
        raise ValueError("Evaluation must contain at least one case with an expected subsystem.")
    return cases


def build_variant(path: Path) -> str:
    source = SERVER.read_text(encoding="utf-8")
    if source.count(SUBSTRING_MATCH) != 1:
        raise ValueError("Expected exactly one published keyword-matching condition.")
    if source.count(RETRIEVAL_TOOL) != 1:
        raise ValueError("Expected exactly one published retrieval tool definition.")
    modified = source.replace(SUBSTRING_MATCH, PLURAL_MATCH)
    modified = modified.replace(RETRIEVAL_TOOL, PLURAL_MATCHER.strip() + "\n\n\n" + RETRIEVAL_TOOL)
    compile(modified, str(path), "exec")
    path.write_text(modified, encoding="utf-8")
    return "".join(difflib.unified_diff(
        source.splitlines(keepends=True), modified.splitlines(keepends=True),
        fromfile="upstream/server.py", tofile="server_whole_word_plural.py",
    ))


async def call_tool(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    if result.isError:
        raise RuntimeError(f"{name} failed: {result.content}")
    payload = result.structuredContent
    if payload is None:
        text_blocks = [part.text for part in result.content if part.type == "text"]
        if len(text_blocks) != 1:
            raise ValueError(f"{name} did not return a single JSON object.")
        payload = json.loads(text_blocks[0])
    if not isinstance(payload, dict):
        raise ValueError(f"{name} did not return an object.")
    return payload


async def run_server(server: Path, cases: list[Case], log: Path) -> dict:
    settings = StdioServerParameters(command=sys.executable, args=[str(server)])
    with log.open("w", encoding="utf-8") as log_file:
        async with asyncio.timeout(45):
            async with stdio_client(settings, errlog=log_file) as (read, write):
                async with ClientSession(read, write) as session:
                    initialization = await session.initialize()
                    tools = await session.list_tools()
                    subsystems = await call_tool(session, "list_subsystems", {})
                    unknown = {label for case in cases for label in case.expected_subsystems} - subsystems.keys()
                    if unknown:
                        raise ValueError(f"Unknown labels: {', '.join(sorted(unknown))}")
                    results = {}
                    for case in cases:
                        response = await call_tool(
                            session, "find_relevant_context", {"task_description": case.query},
                        )
                        results[case.id] = {"retrieval": response}
                        matches = response["relevant_subsystems"]
                        if case.group == "documented_examples" and matches:
                            results[case.id]["files_for_first_match"] = await call_tool(
                                session, "get_files_for_subsystem", {"subsystem": matches[0]["subsystem"]},
                            )
    return {
        "protocol_version": initialization.protocolVersion,
        "server_name": initialization.serverInfo.name,
        "tools": [tool.name for tool in tools.tools],
        "subsystems": subsystems,
        "results": results,
    }


def score_cases(variant: str, cases: list[Case], result: dict) -> list[dict]:
    rows = []
    for case in cases:
        response = result["results"][case.id]["retrieval"]
        recommendations = [match["subsystem"] for match in response["relevant_subsystems"]]
        expected = set(case.expected_subsystems)
        rows.append({
            "variant": variant,
            "group": case.group,
            "id": case.id,
            "query": case.query,
            "expected_subsystems": "|".join(case.expected_subsystems),
            "returned_subsystems": "|".join(recommendations),
            "top1_hit": int(bool(expected.intersection(recommendations[:1]))) if expected else None,
            "top3_hit": int(bool(expected.intersection(recommendations[:3]))) if expected else None,
            "irrelevant_top3_count": len(set(recommendations[:3]) - expected),
            "false_recommendation": int(bool(recommendations)) if not expected else None,
            "notes": case.notes,
            "source": case.source,
        })
    return rows


def summarize(variant: str, rows: list[dict]) -> dict:
    rows = [row for row in rows if row["group"] == "evaluation"]
    positives = [row for row in rows if row["top1_hit"] is not None]
    negatives = [row for row in rows if row["false_recommendation"] is not None]
    top1 = sum(row["top1_hit"] for row in positives)
    top3 = sum(row["top3_hit"] for row in positives)
    false_recommendations = sum(row["false_recommendation"] for row in negatives)
    return {
        "variant": variant,
        "positive_cases": len(positives),
        "top1_hits": top1,
        "top1_rate": round(top1 / len(positives), 6),
        "top3_hits": top3,
        "top3_rate": round(top3 / len(positives), 6),
        "negative_cases": len(negatives),
        "negative_cases_with_recommendations": false_recommendations,
        "negative_false_recommendation_rate": round(false_recommendations / len(negatives), 6) if negatives else None,
        "irrelevant_top3_positive_total": sum(row["irrelevant_top3_count"] for row in positives),
        "irrelevant_top3_total": sum(row["irrelevant_top3_count"] for row in rows),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "cases.json")
    parser.add_argument("--out", type=Path, help="New directory for this run's results")
    args = parser.parse_args()
    cases = load_cases(args.cases)
    started = datetime.now(timezone.utc)
    output = args.out or ROOT / "runs" / started.strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    evaluation_count = sum(case.group == "evaluation" for case in cases)
    example_count = len(cases) - evaluation_count
    print(f"Running local MCP experiment | {evaluation_count} evaluation cases + "
          f"{example_count} documented examples | {output.resolve()}", flush=True)

    results = {}
    with TemporaryDirectory(prefix="project27-") as directory:
        modified = Path(directory) / "server_whole_word_plural.py"
        patch = build_variant(modified)
        modified_sha = sha256(modified)
        (output / "whole_word_plural.diff").write_text(patch, encoding="utf-8")
        for variant, server in (("original", SERVER), ("whole_word_plural", modified)):
            print(f"Calling {variant} MCP server...", flush=True)
            results[variant] = await run_server(server, cases, output / f"mcp_{variant}.log")

    original = results["original"]
    modified_result = results["whole_word_plural"]
    if original["subsystems"] != modified_result["subsystems"] or original["tools"] != modified_result["tools"]:
        raise RuntimeError("The two MCP servers exposed different indices or tool lists.")
    rows, metrics = [], []
    for variant, result in results.items():
        scored = score_cases(variant, cases, result)
        rows.extend(scored)
        metrics.append(summarize(variant, scored))
    write_csv(output / "case_results.csv", rows)
    write_csv(output / "metrics.csv", metrics)
    write_json(output / "raw_mcp.json", results)
    write_json(output / "run.json", {
        "started_at_utc": started.isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mcp_sdk": version("mcp"),
        "protocol_version": original["protocol_version"],
        "transport": "local stdio",
        "author_repo": AUTHOR_REPO,
        "author_commit": AUTHOR_COMMIT,
        "author_server_sha256": sha256(SERVER),
        "modified_server_sha256": modified_sha,
        "cases_file": args.cases.name,
        "cases_sha256": sha256(args.cases),
        "evaluation": "Fixed, locally labeled questions; documentation examples excluded from aggregate metrics.",
    })

    print()
    for row in metrics:
        summary = (f'{row["variant"]}: Top-1 {row["top1_hits"]}/{row["positive_cases"]}, '
                   f'Top-3 {row["top3_hits"]}/{row["positive_cases"]}, '
                   f'unlabeled Top-3 candidates {row["irrelevant_top3_positive_total"]}')
        if row["negative_cases"]:
            summary += (f', false recommendations '
                        f'{row["negative_cases_with_recommendations"]}/{row["negative_cases"]}')
        print(summary)
    print(f"Results saved to {output.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
