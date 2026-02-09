#!/usr/bin/env python3
"""Print one markdown table row from a canonical results.json. Uses env RESULTS_FILE and PLATFORM."""
import json
import os

def main():
    p = os.environ.get("PLATFORM", "?")
    f = os.environ.get("RESULTS_FILE", "")
    if not f:
        print("| ? | — | — | — | — | — |")
        return
    try:
        with open(f) as fp:
            d = json.load(fp)
        a = d.get("aggregates", {})
        b = a.get("by_implementation", {})
        if not b:
            print(f"| {p} | — | — | — | — | — |")
            return
        s = next(iter(b.values()))
        passed = s.get("passed", 0)
        failed = s.get("failed", 0)
        skipped = s.get("skipped", 0)
        total = passed + failed + skipped
        rate = (passed / total * 100) if total else 0
        print(f"| {p} | {passed} | {failed} | {skipped} | {total} | {rate:.1f}% |")
    except Exception:
        print(f"| {p} | — | — | — | — | — |")

if __name__ == "__main__":
    main()
