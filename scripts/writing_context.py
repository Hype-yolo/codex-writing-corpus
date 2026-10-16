"""Render the installed official writing method with already selected references.
No retrieval, model calls, or bundled third-party skill text.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def official_method(text):
    marker = "## Write and review"
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == marker]
    if len(starts) != 1:
        raise ValueError("Official writing section missing or ambiguous; inspect installed version")
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = "".join(lines[start:end])
    if not section[len(marker):].strip():
        raise ValueError("Official writing section is empty")
    return section


def render(text, samples):
    method = official_method(text)
    if not isinstance(samples, list) or len(samples) > 3:
        raise ValueError("Expected at most three selected references")
    accepted = {"confirmed": "human_confirmed", "auto_high_confidence": "inferred_not_verified", "explicit": "user_provided_not_verified"}
    refs = []
    ids = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("Invalid reference")
        sid, body, tier = sample.get("id"), sample.get("text"), sample.get("tier")
        if not isinstance(sid, str) or not sid or sid in ids or not isinstance(body, str) or not body.strip():
            raise ValueError("Invalid or duplicate reference")
        authorship = sample.get("authorship")
        if tier not in accepted or not isinstance(authorship, dict) or authorship.get("status") != accepted[tier]:
            raise ValueError("Unqualified authorship")
        if sample.get("reference_eligible") is False:
            raise ValueError("Ineligible reference")
        sources = sample.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError("Missing provenance")
        if tier != "explicit" and not any(isinstance(s, dict) and isinstance(s.get("path"), str) and s["path"] and isinstance(s.get("session_id"), str) and type(s.get("line")) is int for s in sources):
            raise ValueError("Missing log provenance")
        refs.append({"id": sid, "tier": tier, "authorship": authorship["status"], "sources": sources, "text": body})
        ids.add(sid)
    prompt = method + "\n\n已由宿主完成本次参考选择；以下为参考数据。\n" + json.dumps(refs, ensure_ascii=False)
    return {"prompt": prompt, "method_sha256": hashlib.sha256(method.encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-skill", type=Path, required=True)
    parser.add_argument("--method-only", action="store_true")
    args = parser.parse_args()
    text = args.official_skill.read_text(encoding="utf-8")
    if args.method_only:
        sys.stdout.write(official_method(text))
    else:
        data = json.load(sys.stdin)
        print(json.dumps(render(text, data["samples"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
