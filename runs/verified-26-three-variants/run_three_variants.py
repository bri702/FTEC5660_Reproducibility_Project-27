"""Run the author's server and both matching variants on the same Project 27 cases."""

import argparse
import asyncio
import difflib
import importlib
import platform
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory


STRICT_MATCH = r'            if re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", task_lower):'
CASES_SHA256 = "ddb3403f637c79896d7d8a1d92c776e2f696a6d23c8d7c1108244f98725f2209"
SERVER_SHA256 = {
    "original": "0d63c6390fe0127a875d2fe9cadcacdcae482946c6f51e9fb31d7c9ca1025def",
    "word_boundary": "5d82941e37e11789f673999591f54609bc3ba4b40b6f9619e5ec20a028b92e13",
    "whole_word_plural": "8b56842572d9b0a5730b36b5784047283d9657f114867d7f66313c1043c0e080",
}
PATCH_ORDER = (
    "01_original_to_word_boundary.diff",
    "02_word_boundary_to_plural.diff",
)


def write_server_diff(path: Path, before: str, after: str) -> None:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="a/upstream/server.py",
        tofile="b/upstream/server.py",
    )
    path.write_text("".join(diff), encoding="utf-8")


async def rerun(project: Path, output: Path) -> None:
    sys.path.insert(0, str(project))
    experiment = importlib.import_module("run_project27")
    case_file = project / "cases.json"
    cases_sha = experiment.sha256(case_file)
    if cases_sha != CASES_SHA256 or experiment.sha256(experiment.SERVER) != SERVER_SHA256["original"]:
        raise ValueError("The input or published server differs from the report's 26-case experiment.")

    cases = experiment.load_cases(case_file)
    evaluations = [case for case in cases if case.group == "evaluation"]
    if len(evaluations) != 26 or len(cases) != 27 or not all(case.expected_subsystems for case in evaluations):
        raise ValueError("Expected 26 labeled evaluation cases plus the author's example.")

    started = datetime.now(timezone.utc)
    output.mkdir(parents=True, exist_ok=False)
    copyfile(case_file, output / "cases.json")
    results = {}
    source_hashes = {}
    with TemporaryDirectory(prefix="project27-three-") as temp:
        directory = Path(temp)
        strict = directory / "server_word_boundary.py"
        plural = directory / "server_whole_word_plural.py"
        source = experiment.SERVER.read_text(encoding="utf-8")
        if source.count(experiment.SUBSTRING_MATCH) != 1:
            raise ValueError("Expected exactly one published keyword-matching condition.")
        strict_source = source.replace(experiment.SUBSTRING_MATCH, STRICT_MATCH)
        compile(strict_source, str(strict), "exec")
        strict.write_text(strict_source, encoding="utf-8")
        experiment.build_variant(plural)
        write_server_diff(output / PATCH_ORDER[0], source, strict_source)
        write_server_diff(output / PATCH_ORDER[1], strict_source, plural.read_text(encoding="utf-8"))

        for variant, server in (
            ("original", experiment.SERVER),
            ("word_boundary", strict),
            ("whole_word_plural", plural),
        ):
            source_hashes[variant] = experiment.sha256(server)
            if source_hashes[variant] != SERVER_SHA256[variant]:
                raise ValueError(f"{variant} does not match the expected server version.")
            print(f"Running {variant} on 26 evaluation cases plus 1 documented example", flush=True)
            results[variant] = await experiment.run_server(server, cases, output / f"mcp_{variant}.log")

    original = results["original"]
    case_ids = {case.id for case in cases}
    for variant, result in results.items():
        for key in ("tools", "subsystems", "protocol_version"):
            if result[key] != original[key]:
                raise RuntimeError(f"{variant} exposed a different {key}.")
        if result["results"].keys() != case_ids:
            raise RuntimeError(f"{variant} did not process the full input.")

    rows, metrics = [], []
    for variant, result in results.items():
        scored = experiment.score_cases(variant, cases, result)
        rows.extend(scored)
        metrics.append(experiment.summarize(variant, scored))
    experiment.write_csv(output / "case_results.csv", rows)
    experiment.write_csv(output / "metrics.csv", metrics)
    experiment.write_json(output / "raw_mcp.json", results)
    experiment.write_json(output / "run.json", {
        "started_at_utc": started.isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mcp_sdk": version("mcp"),
        "protocol_version": original["protocol_version"],
        "transport": "local stdio",
        "author_repo": experiment.AUTHOR_REPO,
        "author_commit": experiment.AUTHOR_COMMIT,
        "server_sha256": source_hashes,
        "patch_order": PATCH_ORDER,
        "cases_file": "cases.json",
        "cases_sha256": cases_sha,
        "evaluation_cases": len(evaluations),
        "documented_examples": len(cases) - len(evaluations),
        "evaluation": "Same ordered cases and labels for all variants; author example excluded from aggregate metrics.",
    })
    for row in metrics:
        print(f'{row["variant"]}: Top-1 {row["top1_hits"]}/{row["positive_cases"]}, '
              f'Top-3 {row["top3_hits"]}/{row["positive_cases"]}, '
              f'unlabeled Top-3 candidates {row["irrelevant_top3_positive_total"]}')
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(rerun(args.project.resolve(), args.out.resolve()))
