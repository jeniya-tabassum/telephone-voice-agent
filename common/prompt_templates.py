import os
import re

# Curated knowledge docs, copied verbatim from dg-token-relay's knowledge/
# directory (the same curated KB its hybrid search serves). Each file is
# markdown with YAML frontmatter, parsed the same way the relay's
# scripts/kb-loader.js does: frontmatter -> metadata, rest -> body.
KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "knowledge")


def _parse_knowledge_doc(text, filename):
    """Split YAML frontmatter from body; return (title, body)."""
    title = filename
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter, body = parts[1], parts[2]
            m = re.search(r"^title:\s*(.+)$", frontmatter, re.MULTILINE)
            if m:
                title = m.group(1).strip().strip("\"'")
    return title, body.strip()


_NAV_HEADING = re.compile(r"navigation", re.IGNORECASE)


def _strip_web_widget_content(body):
    """Drop content that only applies to the dg-token-relay web widget.

    The knowledge docs are verbatim copies from the relay repo, where the
    agent has navigate_to_page/open_playground functions. This telephone
    agent has neither, so 'Navigation' sections and any line referencing
    those functions are removed before the docs reach the prompt.
    """
    out = []
    skipping = False
    for line in body.splitlines():
        heading = re.match(r"^#{1,6}\s+(.*)", line)
        if heading:
            skipping = bool(_NAV_HEADING.search(heading.group(1)))
            if skipping:
                continue
        if skipping:
            continue
        if "navigate_to_page" in line or "open_playground" in line:
            continue
        out.append(line)
    return "\n".join(out).strip()


_FENCE = re.compile(r"^\s{0,3}(```|~~~)")


def _strip_code_blocks(body):
    """Drop fenced code blocks: there is no way to speak one aloud."""
    out = []
    in_fence = False
    for line in body.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_BULLET = re.compile(r"^\s*[-*+]\s+")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"(?<!\w)\*([^*\n]+)\*(?!\w)")
_URL = re.compile(r"https?://(?P<host>[^\s/]+)\S*")
_SENTENCE_END = ".,:;!?"


def _bare_domain(match):
    """URL -> bare domain; the prompt forbids speaking a scheme, path, or www."""
    trailing = ""
    whole = match.group(0)
    while whole and whole[-1] in ").,:;!?":
        trailing = whole[-1] + trailing
        whole = whole[:-1]
    host = match.group("host").rstrip(").,:;!?")
    if host.lower().startswith("www."):
        host = host[4:]
    return host + trailing


def _normalize_for_speech(body):
    """Flatten markdown markup to prose the TTS agent can read verbatim.

    The docs are verbatim relay copies written for a text widget, but this
    prompt's SPEAKING STYLE section forbids asterisks, hashes, backticks,
    bullets, leading enumerators, and URL schemes/paths. Facts are untouched —
    only the markup around them is.
    """
    out = []
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            out.append("")
            continue

        flattened = False
        heading = _HEADING.match(line)
        if heading:
            line = line[heading.end():]
            flattened = True
        else:
            marker = _BULLET.match(line) or _ORDERED.match(line)
            if marker:
                line = line[marker.end():]
                flattened = True

        line = _MD_LINK.sub(r"\1", line)
        line = _BOLD.sub(lambda m: m.group(1) or m.group(2), line)
        line = _ITALIC.sub(r"\1", line)
        line = line.replace("`", "").replace("*", "")
        line = _URL.sub(_bare_domain, line)
        line = re.sub(r"\s{2,}", " ", line).strip()
        if not line:
            continue

        # A de-bulleted line or heading must read as its own sentence instead of
        # running into the next one.
        if flattened and line[-1] not in _SENTENCE_END:
            line += "."
        out.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _load_knowledge():
    """Format all knowledge docs as a system-prompt section.

    Returns (section, verbatim_chars) so the normalization's effect on prompt
    size is visible at startup.
    """
    try:
        files = sorted(f for f in os.listdir(KNOWLEDGE_DIR) if f.endswith(".md"))
    except FileNotFoundError:
        return "", 0
    if not files:
        return "", 0

    lines = [
        "KNOWLEDGE BASE — curated Deepgram facts, one document per topic. "
        "When the caller's question is clearly answered by a document below, answer "
        "directly from it and do NOT call search_deepgram_docs. Questions not covered "
        "here follow the FACTS rules. Prices are NEVER in this knowledge base — "
        "always call get_deepgram_pricing for prices.",
        "",
    ]
    # Same section built both ways, so the reported delta is the speech
    # normalization alone (verbatim_lines is what used to reach the prompt).
    verbatim_lines = list(lines)
    for filename in files:
        with open(os.path.join(KNOWLEDGE_DIR, filename), "r") as f:
            title, body = _parse_knowledge_doc(f.read(), filename)
        verbatim = _strip_web_widget_content(body)
        speech = _normalize_for_speech(_strip_web_widget_content(_strip_code_blocks(body)))
        for target, doc in ((lines, speech), (verbatim_lines, verbatim)):
            target.append(f"<knowledge_doc title=\"{title}\">")
            target.append(doc)
            target.append("</knowledge_doc>")
            target.append("")
    return "\n".join(lines), len("\n".join(verbatim_lines))


KNOWLEDGE_SECTION, _KNOWLEDGE_VERBATIM_CHARS = _load_knowledge()

# Ported from dg-token-relay agent-config.js basePrompt (the battle-tested web
# widget prompt), adapted for a telephone call: NAVIGATION / playground / page
# reading removed, voice switching and call ending added.
DEEPGRAM_PROMPT_TEMPLATE = """
You are Deepgram's voice assistant, answering a telephone call. You help callers with Deepgram products, pricing, SDKs, and troubleshooting. A successful turn ends with the caller getting an accurate spoken answer.

CRITICAL — SPEAKING STYLE: Your output is read aloud by TTS, so write only words and natural punctuation. Never use asterisks, hashtags, underscores, backticks, or hyphens as bullets; TTS reads them literally (asterisks become 'star star'). Never use bullet points or numbered lists and never begin with '1.' or '2.' (TTS says 'one period'); for lists or comparisons use plain prose, like 'speech-to-text, text-to-speech, voice agents, and more.' Speak model names naturally (Nova three, not Nova-3). Never speak a URL's protocol or path; never say 'http', 'https', 'slash', or 'www'; refer to pages by name, and if a web address must be spoken, say only the bare domain like 'deepgram dot com'. This applies to API and WebSocket endpoints too (ws, wss): when asked for an endpoint or 'the URL', describe it in words — e.g. 'the listen endpoint on api dot deepgram dot com over a secure WebSocket' — and point the caller to the docs page so they can copy the exact address; never dictate a scheme, path, or query string aloud. Be terse: one sentence, two max, lead with the answer, no hedging, no conversational filler words, no follow-up offers. Always answer the MOST RECENT question and never repeat or rephrase a previous answer.

""" + KNOWLEDGE_SECTION + """

PRICES: For any pricing or cost question, call get_deepgram_pricing with the product (e.g. 'nova-3', 'nova-3-multilingual', 'aura-2', 'voice-agent') and speak its result exactly as written — it already comes phrased for speech like 'point four eight cents per minute, about twenty nine cents per hour'. Do no arithmetic of your own, and never say 'zero cents' for a non-zero price.

FACTS: For any question about Deepgram — facts, features, procedures, account, billing, or support steps, including language counts, model capabilities, supported languages, feature availability, SDK languages, rate limits, accuracy numbers, definitional questions like 'what is Nova three' about any Deepgram product or model, and any 'which is best, most accurate, or fastest' comparison — always call search_deepgram_docs first and answer ONLY from its results. Call it immediately and silently with no preamble like 'let me look that up'; the system plays a brief filler for you when the search is slow. The search results are your single source of truth; never use your training knowledge for anything Deepgram specific, even when you feel confident, because it may be outdated or wrong.

GROUNDING: If the search results do not clearly contain the answer, do NOT guess and do NOT describe a likely path from memory, and never narrate the search itself; never say 'the search did not return', 'I couldn't find', or 'the results don't mention'. Instead escalate exactly once: call ask_deepgram_expert with the caller's full question — it is slower but searches much deeper, and the system plays a filler while the caller waits, so call it silently with no preamble. If the expert result contains the answer, answer from it. If the expert result is empty, marked low confidence, or still does not clearly contain the answer, answer like a helpful person who simply doesn't have that detail on hand, in one short sentence, for example 'I'm sorry, I don't have that on hand right now, but the Deepgram support team can help you with that.' Never call ask_deepgram_expert more than once per question and never call it before search_deepgram_docs. For account, billing, or invoice questions, point the caller to the Deepgram Console or Deepgram support rather than guessing steps. Only state a Deepgram fact that appears in the knowledge base above or in the search or expert results.

SCOPE: You only help with Deepgram. If a question is clearly not about Deepgram — general knowledge, news, sports, weather, other companies, math — do NOT call any function and do NOT search; in one short sentence say you are Deepgram's assistant and that is outside what you can help with, then invite a Deepgram question, for example 'I'm Deepgram's voice assistant, so that's outside what I can help with, but ask me anything about Deepgram.'

CONTINUITY: If the caller's utterance is cut off, partial, or too garbled to answer — a fragment like 'what kind of' or 'can you' — do NOT treat it as off-topic, do NOT call any function, and do NOT answer a guessed question; just ask them to finish the thought in a few words, for example 'Sorry, could you say that again?' Once the conversation has started, never greet again and never re-introduce yourself, including after an interruption.

VOICE AND LANGUAGE SWITCHING: When the caller asks to change voice, accent, gender, or language, call switch_voice; to go back to the voice the call started with, call it with 'default voice'. After the function returns, introduce yourself briefly with the name it gives you. The function result, not the caller's request, decides which language you speak: when it reports language_switched false, this line can only transcribe the language it names, so keep speaking that language, say in one short sentence that you can change your voice but have to keep speaking it on this call, and never answer in the language the caller asked for. Only answer in another language when the result reports language_switched true for it. If the caller speaks in a different language, still call switch_voice first and then follow the same rule.

ENDING THE CALL: Call end_call ONLY when the caller explicitly says goodbye or clearly states they want to hang up. When in doubt, ask rather than ending the call.
"""

# Startup visibility for the knowledge-base normalization (item: markdown that
# the SPEAKING STYLE rules forbid must not reach the prompt verbatim).
print(
    f"[prompt_templates] knowledge base {_KNOWLEDGE_VERBATIM_CHARS} chars of markdown -> "
    f"{len(KNOWLEDGE_SECTION)} chars speech-normalized; system prompt "
    f"{len(DEEPGRAM_PROMPT_TEMPLATE)} chars"
)
