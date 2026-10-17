"""Load explicitly enabled, reviewed local reference snapshots. No discovery or network."""
import copy
import hashlib
import json
from pathlib import Path
import re


def valid_review(review):
    return (isinstance(review, dict) and review.get("status") == "accepted"
            and review.get("method") == "agent_review"
            and isinstance(review.get("reason"), str) and bool(review["reason"].strip()))


def valid_wechat_source(source):
    return (isinstance(source, dict) and source.get("kind") == "wechat"
            and isinstance(source.get("path"), str) and Path(source["path"]).is_absolute()
            and type(source.get("line")) is int and source["line"] > 0
            and isinstance(source.get("conversation_id"), str) and bool(source["conversation_id"].strip())
            and isinstance(source.get("timestamp"), str) and bool(source["timestamp"].strip())
            and "session_id" not in source)


def validate_external_sample(sample):
    if not isinstance(sample, dict):
        raise ValueError("External reference must be an object")
    if not isinstance(sample.get("id"), str) or not sample["id"].strip():
        raise ValueError("External reference requires an id")
    if not isinstance(sample.get("text"), str) or not sample["text"].strip():
        raise ValueError("External reference requires text")
    if (sample.get("tier") != "auto_high_confidence"
            or not isinstance(sample.get("authorship"), dict)
            or sample["authorship"].get("status") != "inferred_not_verified"):
        raise ValueError("External review does not establish human-confirmed authorship")
    if sample.get("reference_eligible") is not True or sample.get("safe") is False:
        raise ValueError("Ineligible external reference")
    if not valid_review(sample.get("review")):
        raise ValueError("External reference requires an accepted agent review with a reason")
    sources = sample.get("sources")
    if not isinstance(sources, list) or not sources or not all(valid_wechat_source(s) for s in sources):
        raise ValueError("External reference requires original WeChat provenance")
    for source in sources:
        if "curated_path" in source and (not isinstance(source["curated_path"], str)
                                           or not Path(source["curated_path"]).is_absolute()):
            raise ValueError("Invalid curated path")
        if "curated_line" in source and (type(source["curated_line"]) is not int or source["curated_line"] <= 0):
            raise ValueError("Invalid curated line")


def load_external_sources(output):
    manifest_path = Path(output) / "external-sources.json"
    stats = {"external_sources_enabled": 0, "external_samples_loaded": 0}
    if not manifest_path.exists():
        return [], stats
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or not isinstance(manifest.get("sources"), list)):
        raise ValueError("Invalid external-sources.json schema; expected schema_version 1 and sources list")
    samples, names, ids = [], set(), set()
    for entry in manifest["sources"]:
        if not isinstance(entry, dict) or type(entry.get("enabled")) is not bool:
            raise ValueError("Every external source requires explicit enabled=true or false")
        if not entry["enabled"]:
            continue
        name, filename, expected = entry.get("name"), entry.get("path"), entry.get("sha256")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("Enabled external sources require unique names")
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError(f"External source {name}: missing path")
        if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
            raise ValueError(f"External source {name}: missing or invalid reviewed sha256")
        path = Path(filename).expanduser()
        if not path.is_absolute():
            path = manifest_path.parent / path
        path = path.resolve()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected.lower():
            raise ValueError(f"External source {name}: sha256 mismatch; review the changed snapshot before enabling it")
        names.add(name)
        stats["external_sources_enabled"] += 1
        # JSONL only splits on LF. U+2028 and similar characters may occur inside strings.
        for line, text in enumerate(raw.decode("utf-8").split("\n"), 1):
            if not text.strip():
                continue
            try:
                sample = json.loads(text)
                validate_external_sample(sample)
                if sample["id"] in ids:
                    raise ValueError("Duplicate external reference id")
            except ValueError as exc:
                raise ValueError(f"External source {name}, line {line}: {exc}") from exc
            ids.add(sample["id"])
            snapshot = {"name": name, "path": str(path), "line": line, "sha256": expected.lower()}
            # Retain attribution per origin when a duplicate body also has a Codex origin.
            for source in sample["sources"]:
                source["authorship"] = copy.deepcopy(sample["authorship"])
                source["review"] = copy.deepcopy(sample["review"])
                source["record_id"] = sample["id"]
                source["reviewed_snapshot"] = snapshot.copy()
            samples.append(sample)
    stats["external_samples_loaded"] = len(samples)
    return samples, stats


def source_key(source):
    kind = source.get("kind", "codex")
    return kind, source.get("conversation_id") or source.get("session_id") or source.get("path")


def merge_same_text(samples, normalize):
    """One reference per identical normalized body, retaining every origin's attribution."""
    by_text, ids = {}, {}
    for original in samples:
        sample = copy.deepcopy(original)
        key = normalize(sample["text"])
        if sample["id"] in ids and ids[sample["id"]] != key:
            raise ValueError("Reference id collision across local corpora")
        ids[sample["id"]] = key
        previous = by_text.get(key)
        if previous is None:
            by_text[key] = sample
            continue
        if sample["tier"] == "confirmed" and previous["tier"] != "confirmed":
            sample, previous = previous, sample
            by_text[key] = previous
        for source in sample["sources"]:
            if source not in previous["sources"]:
                previous["sources"].append(source)
    return list(by_text.values())
