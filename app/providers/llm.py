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

# Mock account data, keyed by phone number (E.164). No real backend yet.
MOCK_ACCOUNTS = {
    "default": {"balance": "1,245.30", "last_transaction": "$42.00 at Whole Foods"},
}

SYSTEM_PROMPT = (
    "You are a phone banking assistant. Be concise (1-2 sentences), "
    "speak naturally since this is a voice call, and never invent "
    "account data that wasn't provided to you."
)


def generate_reply(caller_number: str, user_text: str, history: list[dict]) -> str:
    """Given the caller's utterance, return the assistant's spoken reply."""
    ####################intent layer with json output############################################

    #############################################################################################

    ##################### bank endpoint layer###################################################
    text = user_text.lower()
    account = MOCK_ACCOUNTS.get(caller_number, MOCK_ACCOUNTS["default"])
    ############################################################################################

    if "balance" in text:
        return f"Your current balance is ${account['balance']}."

    if "last transaction" in text or "recent transaction" in text:
        return f"Your most recent transaction was {account['last_transaction']}."

    if "human" in text or "agent" in text or "representative" in text:
        return "Sure, I'll transfer you to a representative now. Please hold."

    if "hello" in text or "hi" in text:
        return "Hi, I'm your banking assistant. You can ask about your balance or recent transactions."

    return "Sorry, I can help with account balance, recent transactions, or connect you to a human. What would you like?"
