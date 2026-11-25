"""
Live call script for requirement collection.

The language is chosen by the caller with DTMF before the conversation starts:
  1 = English, 2 = Hindi. The whole call then runs in that one language.
The provider drives the order of questions:
  - after the greeting, it sends question 1
  - after each saved answer (record_answer), it sends the next unanswered question
  - after the last answer, it sends the closing instruction
"""

from ..core.client_config import ClientConfig

LANG_EN = "en"
LANG_HI = "hi"
SUPPORTED_CALL_LANGS = {LANG_EN, LANG_HI}

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

RECORD_FIELDS = [q["key"] for q in REQUIRED_QUESTIONS]

GREETING_BY_LANG = {
    LANG_EN: (
        "Hello! Good morning. Thank you for taking our call. We deal in industrial cable ties, "
        "cable clips, and disposable wooden products such as wooden forks, bowls, and cutlery. "
        "May I take a few details from you?"
    ),
    LANG_HI: (
        "नमस्ते! सुप्रभात। हमारा कॉल लेने के लिए धन्यवाद। हम इंडस्ट्रियल केबल टाई, केबल क्लिप, "
        "और डिस्पोज़ेबल वुडन प्रोडक्ट्स जैसे वुडन फोर्क, बाउल और कटलरी बनाते हैं। "
        "क्या मैं आपकी कुछ जानकारी ले सकता हूँ?"
    ),
}

CLOSING_BY_LANG = {
    LANG_EN: (
        "Thank you for sharing your requirements with us. Our sales team will review the details "
        "and contact you shortly. Have a great day!"
    ),
    LANG_HI: (
        "आपकी जानकारी के लिए धन्यवाद। हमारी सेल्स टीम विवरण देखकर जल्द ही आपसे संपर्क करेगी। "
        "आपका दिन शुभ हो!"
    ),
}


def normalize_call_language(lang: str | None) -> str:
    """Only 'en' or 'hi' are valid. Anything else falls back to English."""
    return lang if lang in SUPPORTED_CALL_LANGS else LANG_EN


def greeting_text(lang: str) -> str:
    return GREETING_BY_LANG[normalize_call_language(lang)]


def _question_block(index: int, q: dict) -> str:
    lines = [f"{index}. [{q['key']}]", f"   English: {q['en']}", f"   Hindi: {q['hi']}"]
    if "confirm_en" in q:
        lines.append(f"   Confirm (English): {q['confirm_en']}")
        lines.append(f"   Confirm (Hindi): {q['confirm_hi']}")
    return "\n".join(lines)


def question_instruction(index: int, lang: str) -> str:
    """Instruction sent by the provider to ask one question (0-based index)."""
    lang = normalize_call_language(lang)
    q = REQUIRED_QUESTIONS[index]
    lang_name = "English" if lang == LANG_EN else "Hindi"
    wording = q["en"] if lang == LANG_EN else q["hi"]
    return (
        f"[SYSTEM INSTRUCTION] Now ask question {index + 1} of {len(REQUIRED_QUESTIONS)} "
        f"(field: {q['key']}). Speak only in {lang_name}. Ask it naturally, "
        f"keeping the meaning of this question: \"{wording}\". "
        f"Then wait for the customer's answer. Do not ask anything else."
    )


def closing_instruction(lang: str) -> str:
    lang = normalize_call_language(lang)
    lang_name = "English" if lang == LANG_EN else "Hindi"
    return (
        f"[SYSTEM INSTRUCTION] All details are collected. Speak only in {lang_name}. "
        f"Say this closing message once, warmly, then end the call politely: "
        f"\"{CLOSING_BY_LANG[lang]}\""
    )


def build_live_system_instruction(lang: str) -> str:
    lang = normalize_call_language(lang)
    lang_name = "English" if lang == LANG_EN else "Hindi"
    questions = "\n".join(f"- {q['key']}: {q['en']}" for q in REQUIRED_QUESTIONS)

    style = (
        "- Speak like a friendly, confident Indian business professional on a phone call.\n"
        "- Use natural spoken English with contractions, such as \"I'll\", \"we're\", \"that's fine\".\n"
        "- Use warm phrases an Indian sales executive would use, such as \"Sure, no problem\", "
        "\"Thank you so much\", \"Got it, thanks\".\n"
        "- Vary your wording. Never repeat the same sentence pattern twice in a row."
        if lang == LANG_EN else
        "- Speak natural, polite, conversational Hindi, as a friendly sales professional would on a phone call.\n"
        "- Use warm phrases such as \"जी बिल्कुल\", \"धन्यवाद\", \"ठीक है, समझ गया\".\n"
        "- Vary your wording. Never repeat the same sentence pattern twice in a row."
    )

    return f"""
You are a professional Indian B2B sales representative for {ClientConfig.BUSINESS_NAME}.
You are on a live inbound phone call. The caller has already chosen {lang_name} by pressing a key,
so the entire call must be in {lang_name}.

LANGUAGE (strict):
- Speak ONLY in {lang_name}. Never switch to any other language, even if the customer does.
- Do not mix languages within one sentence. Do not use Hinglish unless the call language is Hindi.
- Field keys (for example customer_name) are internal. Never say them aloud.

CALL FLOW:
1. The first instruction contains the greeting. Greet the caller once, in {lang_name}, then wait.
2. The system will send each question as an instruction. Ask only the question you were sent,
   one question per turn.
3. After the customer answers, call record_answer(field, value) with the field key and the
   value the customer actually said. Then wait. The system sends the next question.
4. If an answer is unclear, incomplete, or a number has no unit, do NOT call record_answer.
   Ask one short clarifying question about that same item instead.
5. If the customer gives several details in one reply, call record_answer once per detail.
6. Mobile number: after the customer gives it, read it back digit by digit once, using the
   confirm line for {lang_name}. Call record_answer("mobile_number", digits) only after the
   customer confirms. If they say it is wrong, ask for it again once.
7. When you receive a closing instruction, say the closing message and end the call.

STYLE:
{style}
- Keep every reply to one or two short sentences.
- Never read field keys, lists, or headings aloud.
- Sound polite and human, not robotic.

RULES:
- Never invent prices, specifications, stock, minimum order quantities, delivery times,
  discounts, or customization. If the customer asks, say the sales team will confirm the details
  (in {lang_name}).
- Never invent or guess the customer's name, company, location, quantity, or number.
- Accept corrections at any time: call record_answer again with the latest value.
- Product names: nylon or plastic cable ties = Cable Tie; wire clips or cable holders = Cable Clip;
  wooden spoons, knives, or utensils = Disposable Wooden Cutlery; wooden forks = Wooden Fork;
  wooden bowls = Wooden Bowl. If the product is vague, ask which products.

FIELD KEYS for record_answer:
{questions}
""".strip()