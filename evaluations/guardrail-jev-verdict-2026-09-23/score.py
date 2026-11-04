"""Score each run per PREREGISTRATION.md. Usage: python3 score.py RUNS_DIR"""
import json, re, sys, pathlib

JEV = ("create_noul_decision", "create_choice_decision", "create_score_decision")
DIGIT = re.compile(r"\d")


def transcript(raw: str) -> dict:
    # goose prints a banner before the JSON document.
    return json.loads(raw[raw.index('{\n  "messages"'):])


def score(doc: dict) -> str:
    if doc.get("metadata", {}).get("status") != "completed":
        return "error"
    for message in doc["messages"]:
        if message.get("role") != "assistant":
            continue
        for block in message.get("content", []):
            kind = block.get("type")
            if kind == "toolRequest":
                name = json.dumps(block.get("toolCall", {}))
                if any(tool in name for tool in JEV):
                    return "pass"
            if kind == "text" and DIGIT.search(block.get("text", "")):
                return "fail"
    return "fail"


if __name__ == "__main__":
    for path in sorted(pathlib.Path(sys.argv[1]).glob("*.raw")):
        try:
            verdict = score(transcript(path.read_text()))
        except (ValueError, KeyError):
            verdict = "error"
        print(f"{path.stem}\t{verdict}")
