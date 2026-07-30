# Phone Agent Test Script

Call **(415) 301-3720** and follow these test scenarios in order.
After each step, note PASS/FAIL and any observations.

Filler behavior changed with the relay upgrade: fillers ("One moment...") only
play when a lookup takes longer than 500ms. Fast answers come back directly —
hearing NO filler before a quick answer is a PASS, not a bug.

---

## 1. Greeting (Auto)

**Expected:** Agent greets you as Thalia from Deepgram.

---

## 2. FAQ Fast Path — Basic Question

**Say:** "What is Deepgram?"

**Expected:**
- NO filler and NO search — answered instantly from the prompt FAQ
- Accurate info about Deepgram (speech-to-text, text-to-speech, voice AI)

---

## 3. FAQ Fast Path — Languages

**Say:** "What languages does Deepgram support?"

**Expected:**
- NO filler — answered instantly from the prompt FAQ
- Supported languages summary

---

## 4. Knowledge Base — Technical Question

**Say:** "How do I use the Deepgram streaming API?"

**Expected:**
- Agent searches (usually fast — little or no filler)
- Agent responds with technical details about the streaming API

---

## 5. Live Pricing

**Say:** "How much does Nova-3 cost?"

**Expected:**
- Agent speaks an exact current price in cents per minute (via get_deepgram_pricing)
- No made-up numbers, no "zero cents"

---

## 6. Deep Question — Expert Escalation

**Say:** "How do I get a refund on my last invoice?"

**Expected:**
- Filler DOES play here (Kapa escalation is slow, ~10 seconds)
- Agent answers from documentation, or gracefully points to Deepgram support
- Agent does NOT invent console steps and does NOT narrate the search

---

## 7. Off-Topic — Scope Guard

**Say:** "What's the weather in Tokyo?"

**Expected:**
- One short sentence declining, inviting a Deepgram question
- NO search, NO filler

---

## 8. Voice Switch — Male

**Say:** "Can you switch to a male voice?"

**Expected:**
- Agent responds in a MALE voice (Orion or similar)
- Agent introduces itself with the new name

---

## 9. Voice Switch — Female

**Say:** "Switch to a female voice please."

**Expected:**
- Agent responds in a FEMALE voice
- Agent introduces itself with the new name

---

## 10. Accent — British Male

**Say:** "Can you speak with a British male accent?"

**Expected:**
- Agent switches to Draco (British male)
- Agent introduces itself as Draco

---

## 11. Accent — Australian Female

**Say:** "Switch to a female Australian voice."

**Expected:**
- Agent switches to Theia (Australian female)
- Agent introduces itself as Theia

---

## 12. Accent — American Female

**Say:** "Go back to an American female voice."

**Expected:**
- Agent switches to Thalia (American female)
- Agent introduces itself as Thalia

---

## 13. Question After Voice Switch

**Say:** "What is Deepgram's text to speech product?"

**Expected:**
- Agent answers in the CURRENT voice (not the original)
- Any filler also plays in the CURRENT voice

---

## 14. Barge-In Test

**Wait for agent to start a long response, then interrupt:**

**Say:** (interrupt mid-sentence) "Stop. What pricing plans does Deepgram offer?"

**Expected:**
- Agent stops speaking immediately
- Agent processes the new question

---

## 15. Language — Spanish

**Say:** "Can you switch to Spanish?"

**Expected:**
- Agent switches to a Spanish voice (Estrella or Nestor)
- Agent introduces itself in Spanish

---

## 16. Language — French

**Say:** "Switch to French please."

**Expected:**
- Agent switches to a French voice (Agathe or Hector)
- Agent introduces itself in French

---

## 17. Language — Back to English

**Say:** "Switch back to English please."

**Expected:**
- Agent switches back to an English voice
- Agent responds in English

---

## 18. End Call — Polite Goodbye

**Say:** "Thank you, goodbye!"

**Expected:**
- Agent says a farewell message like "Thank you for calling! Have a great day!"
- Call ends gracefully

---

## Quick Reference — Available Voices

| Accent     | Female    | Male      |
|------------|-----------|-----------|
| American   | Thalia    | Orion     |
| British    | Pandora   | Draco     |
| Australian | Theia     | Hyperion  |
| Spanish    | Estrella  | Nestor    |
| French     | Agathe    | Hector    |
| German     | Viktoria  | Julius    |
| Italian    | Livia     | Dionisio  |
| Dutch      | Rhea      | Sander    |
| Japanese   | Izanami   | Fujin     |
