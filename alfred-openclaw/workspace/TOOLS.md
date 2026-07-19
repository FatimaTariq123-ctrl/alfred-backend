# TOOLS.md - Alfred's Tools Reference

## Available MCP Tools

### `get_investor_profile`
- **When:** Start of every conversation + any personalization needed
- **Input:** `user_id` (string)
- **Output:** Full Investor DNA JSON with archetype, insights, guidance
- **Important:** Always load this first before any other tool

### `create_investor_profile`
- **When:** New user onboarding or profile update request
- **Input:** `user_id` + answers to all 6 onboarding questions (q1-q4 + follow-ups)
- **Output:** Full Investor DNA JSON saved to database
- **Question values:**
  - q1: 1=Growing savings, 2=Monthly income, 3=Goal in 1-3 years, 4=Learning
  - q2: 1=Steadier path, 2=Balanced, 3=Ambitious, 4=Not sure
  - q3: 1=Stressed at any loss, 2=Small swings ok, 3=Bigger swings ok, 4=Long-term focus
  - q3_followup: 1=Protect first, 2=Grow steadily, 3=Grow faster
  - q4: 1=Very little, 2=Some room, 3=Good room
  - q4_followup: 1=No emergency fund, 2=A little, 3=3 months, 4=6+ months

### `run_macro_context`
- **When:** Any macro, fundamental, geopolitical, or "why is X moving" question
- **Input:** `user_question` (string) + `user_id` (string)
- **Output:** Analysis + "What this means for [Archetype]" + ui_card + voice_script
- **Always:** Personalized to user's Investor DNA profile

### `run_fact_guard`
- **When:** ALWAYS — every response before delivery, no exceptions
- **Input:** `agent_output` (object) + `user_id` (string)
- **Output:** PASS | MINOR_FIX (with corrections) | REJECT (with reason)
- **Rule:** Only deliver to user if PASS or MINOR_FIX

### `translate_trade_intent`
- **When:** Any request to buy, sell, trade, or place an order
- **Input:** `user_text` (string) + optional `user_id` (string)
- **Output:** `valid`, `payload`, `errors`, and `guardrail_handoff`
- **Rule:** Always use this tool before any trade execution or guardrail evaluation

### `run_guardrail_guard`
- **When:** A valid structured trade payload exists from `translate_trade_intent`
- **Input:** `action_request` (object)
- **Output:** Guardrail decision payload with `decision`, `approved`, and `reason_code`
- **Rule:** Use the router's `guardrail_handoff` payload directly; do not send conversational text

## Archetypes Reference
| Archetype | Risk | Target | Tone |
|---|---|---|---|
| Guided Starter | Low | ~5% | Encouraging, educational |
| Steady Builder | Low | ~8% | Reassuring, protective |
| Balanced Builder | Medium | ~15% | Balanced, disciplined |
| Ambitious Builder | High | ~25% | Confident, forward-looking |

## Formatting Rules
- WhatsApp: No markdown tables, use bullet lists, no headers
- Dashboard: Full markdown supported
- Always end with "So what this means for you..." tie-in
- Short paragraphs, plain language for ages 12-80

## Output Handling Rules

When any MCP tool returns a JSON response:

### Always extract and use these fields:
- `ui_card.title` → use as the response headline
- `ui_card.body` → use as the main summary
- `voice_script` → use as your spoken response verbatim
- `what_this_means` → always include this section for the user
- `risk_note` → always append this at the end

### Never:
- Rewrite or paraphrase the voice_script
- Ignore the ui_card structure
- Skip the risk_note
- Add your own analysis on top of the agent output

### Response format:
**[ui_card.title]**
[ui_card.body]

[what_this_means]

_[risk_note]_