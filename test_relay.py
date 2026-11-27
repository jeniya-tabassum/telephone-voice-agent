"""
Smoke test for the dg-token-relay knowledge functions the agent uses.

Hits the live relay (RELAY_BASE, default https://token-relay.deepgram.com)
through the same code path the voice agent uses (common.agent_functions),
verifying response shape and printing per-call latency.

Usage:
    python test_relay.py
    RELAY_BASE=https://deepgram-token-relay.fly.dev python test_relay.py
"""

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from common.agent_functions import (
    search_deepgram_docs,
    ask_deepgram_expert,
    get_deepgram_pricing,
)
from common.config import RELAY_BASE, FILLER_THRESHOLD_SECONDS

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def report(name, result, expect_results=True):
    ok = bool("error" not in result and (result.get("results") or not expect_results))
    latency = result.get("latency_seconds", -1)
    color = GREEN if ok else RED
    filler_note = (
        f"{YELLOW}(filler would fire){RESET}"
        if latency >= FILLER_THRESHOLD_SECONDS
        else f"{GREEN}(no filler needed){RESET}"
    )
    print(f"  {color}{'PASS' if ok else 'FAIL'}{RESET} {name}: "
          f"{len(result.get('results', []))} chunks in {latency}s {filler_note}")
    if not ok:
        print(f"       {result.get('error', 'empty results')}")
    else:
        first = result["results"][0]
        print(f"       top: [{first.get('title', '')[:60]}] {first.get('content', '')[:100]}...")
    return ok


async def main():
    print(f"\nRelay: {RELAY_BASE}\n")
    passed = 0
    total = 0

    # Fast local-index path (should be well under the filler threshold)
    for q in ["What is Nova-3?", "What languages does Nova-3 Multilingual support?"]:
        total += 1
        result = await search_deepgram_docs({"query": q})
        passed += report(f'search "{q}"', result)

    # Off-index query — exercises the Kapa merge path (slower, filler covers it)
    total += 1
    result = await search_deepgram_docs({"query": "How do I get a refund on my invoice?"})
    passed += report('search "refund invoice" (merge path)', result)

    # Live pricing
    total += 1
    result = await get_deepgram_pricing({"product": "nova-3"})
    passed += report("pricing nova-3", result)

    # Expert escalation (~10s; run last, optional via --skip-expert)
    if "--skip-expert" not in sys.argv:
        total += 1
        result = await ask_deepgram_expert({"query": "What is the minimum monthly commitment for Deepgram enterprise plans?"})
        passed += report("expert escalation", result)

    print(f"\n{passed}/{total} passed\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
