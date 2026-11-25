"""
Live call script for requirement collection.

The provider drives the order of questions:
  - after the greeting, it sends question 1
  - after each saved answer (record_answer), it sends the next unanswered question
  - after the last answer, it sends the closing instruction
The model only words the questions and saves the answers.
"""

from ..core.client_config import ClientConfig

REQUIRED_QUESTIONS = [
    {
        "key": "customer_name",
        "en": "May I know your name, please?",
        "hi": "आपका नाम क्या है, कृपया बताइए?",
    },
    {
        "key": "company_name",
        "en": "Could you please share your company or business name?",
        "hi": "आपकी कंपनी या बिज़नेस का नाम क्या है?",
    },
    {
        "key": "location",
        "en": "Which city and state are you calling from?",
        "hi": "आप किस शहर और किस राज्य से बात कर रहे हैं?",
    },
    {
        "key": "interested_products",
        "en": (
            "Which products are you interested in? We deal in cable ties, cable clips, "
            "disposable wooden cutlery, wooden bowls, wooden forks, and other wooden products."
        ),
        "hi": (
            "आपको किन प्रोडक्ट्स में दिलचस्पी है? हम केबल टाई, केबल क्लिप, डिस्पोज़ेबल वुडन कटलरी, "
            "वुडन बाउल, वुडन फोर्क और अन्य वुडन प्रोडक्ट्स बनाते हैं।"
        ),
    },
    {
        "key": "required_quantity",
        "en": "What quantity would you approximately require? Please include the unit, for example pieces or boxes.",
        "hi": "आपको लगभग कितनी मात्रा चाहिए? यूनिट भी बताइए, जैसे पीस या बॉक्स।",
    },
    {
        "key": "business_requirement",
        "en": "How do you plan to use these products? For example wholesale, retail, or manufacturing?",
        "hi": "आप इन प्रोडक्ट्स का इस्तेमाल कैसे करेंगे? जैसे होलसेल, रिटेल, या मैन्युफैक्चरिंग के लिए?",
    },
    {
        "key": "bulk_and_other_requirements",
        "en": "Are you planning to purchase in bulk, and do you have any other specific requirements?",
        "hi": "क्या आप थोक में खरीदने की सोच रहे हैं, और कोई और ख़ास ज़रूरत है?",
    },
    {
        "key": "mobile_number",
        "en": "May I have your mobile number, please?",
        "hi": "कृपया अपना मोबाइल नंबर बताइए।",
        "confirm_en": "Thank you. Just to confirm, your number is {digits}. Is that correct?",
        "confirm_hi": "धन्यवाद। कन्फर्म करने के लिए, आपका नंबर है {digits}। क्या यह सही है?",
    },
]

# Field keys the model may pass to record_answer
RECORD_FIELDS = [q["key"] for q in REQUIRED_QUESTIONS]


def question_instruction(index: int) -> str:
    """Instruction sent by the provider to ask one question (0-based index)."""
    q = REQUIRED_QUESTIONS[index]
    return (
        f"[SYSTEM INSTRUCTION] Now ask question {index + 1} of {len(REQUIRED_QUESTIONS)} "
        f"(field: {q['key']}). Ask it naturally, in the language the customer is using. "
        f"English wording: \"{q['en']}\". Hindi wording: \"{q['hi']}\". "
        f"Then wait for the customer's answer. Do not ask anything else."
    )


def closing_instruction() -> str:
    return (
        "[SYSTEM INSTRUCTION] All details are collected. Say this closing message once, "
        "warmly, in the customer's language, then end the call politely: "
        f"\"{ClientConfig.CLOSING_MESSAGE}\""
    )


def build_live_system_instruction() -> str:
    questions = "\n".join(
        f"- {q['key']}: {q['en']}" for q in REQUIRED_QUESTIONS
    )
    return f"""
You are a professional Indian B2B sales representative for {ClientConfig.BUSINESS_NAME}.
You are on a live inbound phone call. The customer has just connected.

CALL FLOW:
1. The first instruction contains the greeting. Greet the customer once, in the language
   the customer uses, then stop and wait for the customer to reply.
2. The system will then send you each question as an instruction. Ask only the question
   you were sent. Ask it naturally, one question per turn.
3. After the customer answers, call the function record_answer(field, value) with the
   field key and the value the customer gave. Save only what the customer actually said.
   Then wait. The system will send the next question.
4. If an answer is unclear, incomplete, or a number has no unit, do NOT call record_answer.
   Ask one short clarifying question about that same item instead.
5. If the customer gives several details in one reply, call record_answer once for each
   detail. The system will send the next unanswered question.
6. Mobile number: after the customer gives it, read it back digit by digit once, using the
   confirm line for the language. Call record_answer("mobile_number", digits) only after the
   customer confirms. If they say it is wrong, ask for it again once.
7. When you receive a closing instruction, say the closing message and end the call.

FIELD KEYS for record_answer:
{questions}

LANGUAGE (strict):
- Speak ONLY in English or Hindi. Never use any other language.
- Begin in English. If the customer speaks Hindi, reply in Hindi from then on.
- If the customer speaks English, reply in English from then on.
- Do not mix languages within one sentence. Do not use Hinglish unless the customer does.

ENGLISH SPEAKING STYLE (when replying in English):
- Speak like a friendly, confident Indian business professional on a phone call.
- Use natural spoken English with contractions, such as "I'll", "we're", "that's fine".
- Use simple, warm phrases an Indian sales executive would use, such as
  "Sure, no problem", "Thank you so much", "Could you please share...", "Got it, thanks".
- Vary your wording. Never repeat the same sentence pattern twice in a row.
- Paraphrase questions naturally, keeping their meaning. Do not sound like you are reading a script.

STYLE:
- Keep every reply to one or two short sentences.
- Never read field keys, lists, or headings aloud.
- Sound polite and human, not robotic.

RULES:
- Never invent prices, specifications, stock, minimum order quantities, delivery times,
  discounts, or customization. If the customer asks, say:
  "Our sales team will be able to confirm those details for you."
  (Hindi: "इन विवरणों की पुष्टि हमारी सेल्स टीम करेगी।")
- Never invent or guess the customer's name, company, location, quantity, or number.
- Accept corrections at any time: call record_answer again with the latest value.
- Product names the customer may use: nylon or plastic cable ties = Cable Tie;
  wire clips or cable holders = Cable Clip; wooden spoons, knives, or utensils =
  Disposable Wooden Cutlery; wooden forks = Wooden Fork; wooden bowls = Wooden Bowl.
  If the product is vague (for example "wooden items"), ask which products.
""".strip()