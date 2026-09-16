"""
LLM "brain" for the banking assistant.

Prototype stub: simple keyword/intent matching over mock account data,
no real LLM call yet. Swap `generate_reply` internals for a real API
call (Claude, GPT, etc.) once the pipeline is proven end to end.

Real integration sketch:
    resp = anthropic_client.messages.create(
        model=LLM_MODEL,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=conversation_history + [{"role": "user", "content": text}],
    )
    return resp.content[0].text
"""

# Mock account data, keyed by caller phone number (E.164). No real backend yet.
MOCK_ACCOUNTS = {
    "default": {"balance": "1,245.30", "last_transaction": "$42.00 at Whole Foods"},
}

SYSTEM_PROMPT = (
    "You are a phone banking assistant. Be concise (1-2 sentences), "
    "speak naturally since this is a voice call, and never invent "
    "account data that wasn't provided to you."
)

# Intent -> keyword triggers. Checked in order; first match wins.
_INTENT_KEYWORDS = {
    "balance": ("balance",),
    "last_transaction": ("last transaction", "recent transaction"),
    "human_handoff": ("human", "agent", "representative"),
    "greeting": ("hello", "hi"),
}


def _detect_intent(text: str) -> str | None:
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return intent
    return None


def generate_reply(caller_number: str, user_text: str, history: list[dict]) -> str:
    """Given the caller's utterance, return the assistant's spoken reply."""
    text = user_text.lower()
    account = MOCK_ACCOUNTS.get(caller_number, MOCK_ACCOUNTS["default"])
    intent = _detect_intent(text)

    if intent == "balance":
        return f"Your current balance is ${account['balance']}."

    if intent == "last_transaction":
        return f"Your most recent transaction was {account['last_transaction']}."

    if intent == "human_handoff":
        return "Sure, I'll transfer you to a representative now. Please hold."

    if intent == "greeting":
        return "Hi, I'm your banking assistant. You can ask about your balance or recent transactions."

    return "Sorry, I can help with account balance, recent transactions, or connect you to a human. What would you like?"
