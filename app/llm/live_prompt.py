# """
# Live call script for requirement collection.

# The language is chosen by the caller with DTMF before the conversation starts:
#   1 = English, 2 = Hindi. The whole call then runs in that one language.
# The provider drives the order of questions:
#   - after the greeting, it sends question 1
#   - after each saved answer (record_answer), it sends the next unanswered question
#   - after the last answer, it sends the closing instruction
# """

# from ..core.client_config import ClientConfig

# LANG_EN = "en"
# LANG_HI = "hi"
# SUPPORTED_CALL_LANGS = {LANG_EN, LANG_HI}

# REQUIRED_QUESTIONS = [
#     {
#         "key": "customer_name",
#         "en": "May I know your name, please?",
#         "hi": "आपका नाम क्या है, कृपया बताइए?",
#     },
#     {
#         "key": "company_name",
#         "en": "Could you please share your company or business name?",
#         "hi": "आपकी कंपनी या बिज़नेस का नाम क्या है?",
#     },
#     {
#         "key": "location",
#         "en": "Which city and state are you calling from?",
#         "hi": "आप किस शहर और किस राज्य से बात कर रहे हैं?",
#     },
#     {
#         "key": "interested_products",
#         "en": (
#             "Which products are you interested in? We deal in cable ties, cable clips, "
#             "disposable wooden cutlery, wooden bowls, wooden forks, and other wooden products."
#         ),
#         "hi": (
#             "आपको किन प्रोडक्ट्स में दिलचस्पी है? हम केबल टाई, केबल क्लिप, डिस्पोज़ेबल वुडन कटलरी, "
#             "वुडन बाउल, वुडन फोर्क और अन्य वुडन प्रोडक्ट्स में डील करते हैं।"
#         ),
#     },
#     {
#         "key": "required_quantity",
#         "en": "What quantity would you approximately require? Please include the unit, for example pieces or boxes.",
#         "hi": "आपको लगभग कितनी मात्रा चाहिए? यूनिट भी बताइए, जैसे पीस या बॉक्स।",
#     },
#     {
#         "key": "business_requirement",
#         "en": "How do you plan to use these products? For example wholesale, retail, or manufacturing?",
#         "hi": "आप इन प्रोडक्ट्स का इस्तेमाल कैसे करेंगे? जैसे होलसेल, रिटेल, या मैन्युफैक्चरिंग के लिए?",
#     },
#     {
#         "key": "bulk_and_other_requirements",
#         "en": "Are you planning to purchase in bulk, and do you have any other specific requirements?",
#         "hi": "क्या आप थोक में खरीदने की सोच रहे हैं, और कोई और ख़ास ज़रूरत है?",
#     },
#     {
#         "key": "mobile_number",
#         "en": "May I have your mobile number, please?",
#         "hi": "कृपया अपना मोबाइल नंबर बताइए।",
#         "confirm_en": "Thank you. Just to confirm, your number is {digits}. Is that correct?",
#         "confirm_hi": "धन्यवाद। कन्फर्म करने के लिए, आपका नंबर है {digits}। क्या यह सही है?",
#     },
# ]

# RECORD_FIELDS = [q["key"] for q in REQUIRED_QUESTIONS]

# GREETING_BY_LANG = {
#     LANG_EN: (
#         "Hello! Good morning. Thank you for taking our call. We deal in industrial cable ties, "
#         "cable clips, and disposable wooden products such as wooden forks, bowls, and cutlery. "
#         "May I take a few details from you?"
#     ),
#     LANG_HI: (
#         "नमस्ते! सुप्रभात। हमारा कॉल लेने के लिए धन्यवाद। हम इंडस्ट्रियल केबल टाई, केबल क्लिप, "
#         "और डिस्पोज़ेबल वुडन प्रोडक्ट्स जैसे वुडन फोर्क, बाउल और कटलरी बनाते हैं। "
#         "क्या मैं आपकी कुछ जानकारी ले सकती हूँ?"
#     ),
# }

# CLOSING_BY_LANG = {
#     LANG_EN: (
#         "Thank you for sharing your requirements with us. Our sales team will review the details "
#         "and contact you shortly. Have a great day!"
#     ),
#     LANG_HI: (
#         "आपकी जानकारी के लिए धन्यवाद। हमारी सेल्स टीम विवरण देखकर जल्द ही आपसे संपर्क करेगी। "
#         "आपका दिन शुभ हो!"
#     ),
# }


# def normalize_call_language(lang: str | None) -> str:
#     """Only 'en' or 'hi' are valid. Anything else falls back to English."""
#     return lang if lang in SUPPORTED_CALL_LANGS else LANG_EN


# def greeting_text(lang: str) -> str:
#     return GREETING_BY_LANG[normalize_call_language(lang)]


# def _question_block(index: int, q: dict) -> str:
#     lines = [f"{index}. [{q['key']}]", f"   English: {q['en']}", f"   Hindi: {q['hi']}"]
#     if "confirm_en" in q:
#         lines.append(f"   Confirm (English): {q['confirm_en']}")
#         lines.append(f"   Confirm (Hindi): {q['confirm_hi']}")
#     return "\n".join(lines)


# def question_instruction(index: int, lang: str) -> str:
#     """
#     ✅ ENHANCED: Instruction sent by the provider to ask one question (0-based index).
#     Now includes validation requirements and female persona emphasis.
#     """
#     lang = normalize_call_language(lang)
#     q = REQUIRED_QUESTIONS[index]
#     lang_name = "English" if lang == LANG_EN else "Hindi"
#     wording = q["en"] if lang == LANG_EN else q["hi"]
    
#     if lang == LANG_EN:
#         validation = (
#             "If the customer's answer is UNCLEAR (background noise, incoherent), INCOMPLETE (partial name/number), "
#             "or UNRELATED to your question, do NOT call record_answer. Instead, ask once: 'I'm sorry, could you repeat that?' "
#             "If the customer clearly refuses (e.g., 'I won't share that'), call record_answer with 'N/A'."
#         )
#     else:
#         validation = (
#             "अगर ग्राहक का जवाब UNCLEAR है (बैकग्राउंड शोर, अस्पष्ट), INCOMPLETE है (आधा नाम/नंबर), "
#             "या आपके सवाल से UNRELATED है, तो record_answer न करें। बजाय इसके एक बार पूछें: "
#             "'माफ़ कीजिए, आप फिर से बता सकते हैं?' "
#             "अगर ग्राहक साफ़ कह दे कि वह नहीं बता सकता (जैसे 'मैं यह नहीं बता सकती'), "
#             "तो record_answer को 'N/A' के साथ कॉल करें।"
#         )
    
#     return (
#         f"[SYSTEM INSTRUCTION] Now ask question {index + 1} of {len(REQUIRED_QUESTIONS)} "
#         f"(field: {q['key']}). Speak only in {lang_name}. "
#         f"You are a professional FEMALE Indian sales representative. "
#         f"Ask naturally, keeping the meaning of this question: \"{wording}\". "
#         f"Then listen carefully to the customer's answer. "
#         f"{validation} "
#         f"Then wait for the customer's response. Do not ask anything else."
#     )


# def closing_instruction(lang: str) -> str:
#     """
#     ✅ ENHANCED: Closing instruction with emphasis on female persona and language enforcement.
#     """
#     lang = normalize_call_language(lang)
#     lang_name = "English" if lang == LANG_EN else "Hindi"
#     return (
#         f"[SYSTEM INSTRUCTION] All details are collected. Speak only in {lang_name}. "
#         f"You are a professional FEMALE Indian sales representative. "
#         f"Say this closing message once, warmly and naturally, then end the call politely: "
#         f"\"{CLOSING_BY_LANG[lang]}\" "
#         f"Use natural tone. Sound like a real Indian woman, not a robot."
#     )


# def build_live_system_instruction(lang: str) -> str:
#     lang = normalize_call_language(lang)
#     lang_name = "English" if lang == LANG_EN else "Hindi"
#     questions = "\n".join(f"- {q['key']}: {q['en']}" for q in REQUIRED_QUESTIONS)

#     if lang == LANG_EN:
#         style = """- You are a professional FEMALE Indian B2B sales representative.
# - Speak with a natural INDIAN ENGLISH ACCENT. Clear pronunciation, conversational speed.
# - Use warm, polite phrases: "Sure, no problem", "Thank you so much", "Got it, thanks", "That's wonderful".
# - Use natural spoken English with contractions: "I'll", "we're", "that's", "I'm", "you're".
# - Maintain a warm, confident, professional female voice throughout the call.
# - Speak at a moderate, comfortable pace. Never rush.
# - Use natural pauses between sentences. Don't speak in a monotone.
# - Vary your wording. Never repeat the same sentence pattern twice in a row.
# - Sound like a real Indian woman on a professional business phone call.
# - Never sound robotic, monotonic, overly formal, or machine-like."""
#     else:
#         style = """- You are a professional FEMALE Indian B2B sales representative.
# - Speak natural, polite, conversational HINDI with INDIAN pronunciation.
# - FEMALE GRAMMAR: Use feminine first-person forms consistently:
#   * "मैं कर सकती हूँ" (not "कर सकता हूँ")
#   * "मैं समझ सकती हूँ" (not "समझ सकता हूँ")
#   * "मैं नोट कर रही हूँ" (not "कर रहा हूँ")
#   * "मैं बता सकती हूँ" (not "बता सकता हूँ")
#   * "मैं आपकी सहायता कर सकती हूँ" (not "कर सकता हूँ")
# - Use warm, natural Hindi phrases: "जी बिल्कुल", "धन्यवाद", "ठीक है", "बहुत अच्छा".
# - Maintain a warm, confident, professional female voice throughout the call.
# - Speak at a moderate, comfortable pace. Never rush.
# - Use natural pauses between sentences.
# - Vary your wording. Never repeat the same sentence pattern twice in a row.
# - Sound like a real Indian woman on a professional business phone call."""

#     return f"""
# You are a professional FEMALE Indian B2B sales representative for {ClientConfig.BUSINESS_NAME}.
# You are speaking directly with customers over a telephone call.
# You are on a live inbound phone call. The caller has already chosen {lang_name} by pressing a key,
# so the entire call must be in {lang_name}.

# VOICE & ACCENT:
# {style}

# LANGUAGE (STRICT - ENGLISH AND HINDI ONLY):
# - Speak ONLY in {lang_name}. Never switch to any other language under any circumstances.
# - If the customer speaks another language (Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada, etc.),
#   respond ONLY in {lang_name}. Example: "I understand, but I can speak English and Hindi. 
#   Can we continue in {'English' if lang == LANG_EN else 'Hindi'}?"
# - Do not mix languages within one sentence. No Hinglish or code-switching.
# - Field keys (for example customer_name) are internal. Never say them aloud.

# CALL FLOW:
# 1. The first instruction contains the greeting. Greet the caller once, in {lang_name}, then wait.
# 2. The system will send each question as an instruction. Ask only the question you were sent,
#    one question per turn.
# 3. After the customer answers, call record_answer(field, value) with the field key and the
#    value the customer actually said. Then wait. The system sends the next question.
# 4. RESPONSE VALIDATION (CRITICAL):
#    - If an answer is UNCLEAR, INCOMPLETE, UNRELATED, or POORLY HEARD, do NOT call record_answer.
#    - Ask one short clarifying question about that same item instead.
#    - Examples of unclear responses:
#      * Background noise only, no clear words
#      * Incomplete name or quantity
#      * Response unrelated to the current question
#      * Customer's voice too distant or muffled
#      * Only filler words ("umm", "uh", "yeah" without substance)
#    - DO NOT guess or fabricate information. Ask again.
#    - Use confidence: if you're not sure, ask for clarification.
# 5. CUSTOMER REFUSAL HANDLING:
#    - If customer clearly refuses to provide information (e.g., "I don't want to share", "No, I won't provide it"),
#      mark that field as "N/A" by calling record_answer(field, "N/A").
#    - Do NOT keep asking the same question repeatedly.
#    - Distinguish: "No" to bulk purchase = save as "No"; "No, I won't share" = save as "N/A".
# 6. If the customer gives several details in one reply, call record_answer once per detail.
# 7. Mobile number: after the customer gives it, read it back digit by digit once, using the
#    confirm line for {lang_name}. Call record_answer("mobile_number", digits) only after the
#    customer confirms. If they say it is wrong, ask for it again once.
# 8. When you receive a closing instruction, say the closing message and end the call.

# BACKGROUND VOICE HANDLING:
# - Respond only to the customer's voice speaking directly into the phone.
# - Ignore: television audio, radio, background conversations, office noise, distant voices, echoes.
# - Do not treat every sound as a customer response.
# - If VAD captures background noise or unclear speech, verify RELEVANCE and CLARITY:
#   * Check if answer is relevant to current question
#   * Check if speech is clear and coherent (not just noise or fragments)
#   * If unclear: Ask "I'm sorry, could you please repeat that?" once
#   * If multiple speakers: Ask primary customer to continue alone
# - If a different person speaks clearly and answers the current question, accept the answer
#   (legitimate proxy answering). Use conversational context to decide if valid.
# - Short/incomplete responses (<3 words, <1 second) trigger automatic clarification request.
# - Current VAD: SemanticCompletenessAnalyzer detects complete vs incomplete utterances dynamically.
# - Audio filtering: RNNoise + WebRTC noise suppression, bandpass 80-3400 Hz, silence 650ms threshold.

# STYLE & DELIVERY:
# - Keep every reply to one or two short sentences (never long responses).
# - Never read field keys, lists, or headings aloud.
# - Sound polite and human, not robotic.
# - Acknowledge the customer warmly: "Thank you for that information."

# RULES:
# - Never invent prices, specifications, stock, minimum order quantities, delivery times,
#   discounts, or customization. If the customer asks, say the sales team will confirm the details
#   (in {lang_name}).
# - Never invent or guess the customer's name, company, location, quantity, or number.
# - Accept corrections at any time: call record_answer again with the latest value.
# - Product names: nylon or plastic cable ties = Cable Tie; wire clips or cable holders = Cable Clip;
#   wooden spoons, knives, or utensils = Disposable Wooden Cutlery; wooden forks = Wooden Fork;
#   wooden bowls = Wooden Bowl. If the product is vague, ask which products.

# FIELD KEYS for record_answer:
# {questions}
# """.strip()





# """
# Live call script for requirement collection.

# The caller chooses the language with DTMF before the conversation starts:
#   1 = English, 2 = Hindi. The whole call, including greeting and closing, uses that language.

# The provider controls the order of questions:
#   - after the greeting, it sends question 1
#   - after each saved answer (record_answer), it sends the next unanswered question
#   - after the last answer, it sends the closing instruction

# Background speech is handled in two places:
#   - the prompt (this file) tells the model which speech counts as an answer
#   - the caller audio gate (gemini_audio_pipeline.py) reduces quiet background sound
# """

# import os

# from ..core.client_config import ClientConfig

# LANG_EN = "en"
# LANG_HI = "hi"
# SUPPORTED_CALL_LANGS = {LANG_EN, LANG_HI}

# REQUIRED_QUESTIONS = [
#     {
#         "key": "customer_name",
#         "en": "May I know your name, please?",
#         "hi": "आपका नाम क्या है, कृपया बताइए?",
#         "confirm_en": "Just to confirm, your name is {value}. Is that right?",
#         "confirm_hi": "कन्फर्म कर लूँ, आपका नाम {value} है? क्या यह सही है?",
#     },
#     {
#         "key": "company_name",
#         "en": "Could you please share your company or business name?",
#         "hi": "आपकी कंपनी या बिज़नेस का नाम क्या है?",
#         "confirm_en": "Just to confirm, your company name is {value}. Is that right?",
#         "confirm_hi": "कन्फर्म कर लूँ, आपकी कंपनी का नाम {value} है? क्या यह सही है?",
#     },
#     {
#         "key": "location",
#         "en": "Which city and state are you calling from?",
#         "hi": "आप किस शहर और किस राज्य से बात कर रहे हैं?",
#         "confirm_en": "Just to confirm, you are calling from {value}. Is that right?",
#         "confirm_hi": "कन्फर्म कर लूँ, आप {value} से बात कर रहे हैं? क्या यह सही है?",
#     },
#     {
#         "key": "interested_products",
#         "en": (
#             "Which products are you interested in? We deal in cable ties, cable clips, "
#             "disposable wooden cutlery, wooden bowls, wooden forks, and other wooden products."
#         ),
#         "hi": (
#             "आपको किन प्रोडक्ट्स में दिलचस्पी है? हम केबल टाई, केबल क्लिप, डिस्पोज़ेबल वुडन कटलरी, "
#             "वुडन बाउल, वुडन फोर्क और अन्य वुडन प्रोडक्ट्स में डील करते हैं।"
#         ),
#     },
#     {
#         "key": "required_quantity",
#         "en": "What quantity would you approximately require? Please include the unit, for example pieces or boxes.",
#         "hi": "आपको लगभग कितनी मात्रा चाहिए? यूनिट भी बताइए, जैसे पीस या बॉक्स।",
#     },
#     {
#         "key": "business_requirement",
#         "en": "How do you plan to use these products? For example wholesale, retail, or manufacturing?",
#         "hi": "आप इन प्रोडक्ट्स का इस्तेमाल कैसे करेंगे? जैसे होलसेल, रिटेल, या मैन्युफैक्चरिंग के लिए?",
#     },
#     {
#         "key": "bulk_and_other_requirements",
#         "en": "Are you planning to purchase in bulk, and do you have any other specific requirements?",
#         "hi": "क्या आप थोक में खरीदने की सोच रहे हैं, और कोई और ख़ास ज़रूरत है?",
#     },
#     {
#         "key": "mobile_number",
#         "en": "May I have your mobile number, please?",
#         "hi": "कृपया अपना मोबाइल नंबर बताइए।",
#         "confirm_en": "Thank you. Just to confirm, your number is {digits}. Is that correct?",
#         "confirm_hi": "धन्यवाद। कन्फर्म करने के लिए, आपका नंबर है {digits}। क्या यह सही है?",
#     },
# ]

# RECORD_FIELDS = [q["key"] for q in REQUIRED_QUESTIONS]

# # Fields that must be read back and confirmed before they are recorded
# CONFIRM_BEFORE_RECORD = {"customer_name", "company_name", "location", "mobile_number"}

# GREETING_BY_LANG = {
#     LANG_EN: (
#         "Hello! Good morning. Thank you for taking our call. We deal in industrial cable ties, "
#         "cable clips, and disposable wooden products such as wooden forks, bowls, and cutlery. "
#         "May I take a few details from you?"
#     ),
#     LANG_HI: (
#         "नमस्ते! सुप्रभात। हमारा कॉल लेने के लिए धन्यवाद। हम इंडस्ट्रियल केबल टाई, केबल क्लिप, "
#         "और डिस्पोज़ेबल वुडन प्रोडक्ट्स जैसे वुडन फोर्क, बाउल और कटलरी बनाते हैं। "
#         "क्या मैं आपकी कुछ जानकारी ले सकती हूँ?"
#     ),
# }

# CLOSING_BY_LANG = {
#     LANG_EN: (
#         "Thank you for sharing your requirements with us. Our sales team will review the details "
#         "and contact you shortly. Have a great day!"
#     ),
#     LANG_HI: (
#         "आपकी जानकारी के लिए धन्यवाद। हमारी सेल्स टीम विवरण देखकर जल्द ही आपसे संपर्क करेगी। "
#         "आपका दिन शुभ हो!"
#     ),
# }


# def normalize_call_language(lang: str | None) -> str:
#     """Only 'en' or 'hi' are valid. Anything else falls back to English."""
#     return lang if lang in SUPPORTED_CALL_LANGS else LANG_EN


# def _language_name(lang: str) -> str:
#     return "English" if normalize_call_language(lang) == LANG_EN else "Hindi"


# def greeting_text(lang: str) -> str:
#     return GREETING_BY_LANG[normalize_call_language(lang)]


# def closing_text(lang: str) -> str:
#     """
#     English: CLIENT_CLOSING_MESSAGE from .env, if set.
#     Hindi:   CLIENT_CLOSING_MESSAGE_HI from .env, if set.
#     Otherwise the built-in text for the language.
#     """
#     lang = normalize_call_language(lang)
#     if lang == LANG_HI:
#         return os.getenv("CLIENT_CLOSING_MESSAGE_HI", "").strip() or CLOSING_BY_LANG[LANG_HI]
#     env_en = (os.getenv("CLIENT_CLOSING_MESSAGE", "") or getattr(ClientConfig, "CLOSING_MESSAGE", "")).strip()
#     return env_en or CLOSING_BY_LANG[LANG_EN]


# def question_instruction(index: int, lang: str) -> str:
#     """Instruction sent by the provider to ask one question (0-based index)."""
#     lang = normalize_call_language(lang)
#     q = REQUIRED_QUESTIONS[index]
#     lang_name = _language_name(lang)
#     wording = q["en"] if lang == LANG_EN else q["hi"]

#     if lang == LANG_EN:
#         unclear = (
#             "If the reply is unclear, cut off, or not an answer to this question, do not record it. "
#             "Say once: \"Sorry, I didn't catch that. Could you please repeat?\""
#         )
#     else:
#         unclear = (
#             "अगर जवाब अस्पष्ट है, अधूरा है, या इस सवाल का जवाब नहीं है, तो उसे रिकॉर्ड न करें। "
#             "एक बार कहें: \"माफ़ कीजिए, मुझे ठीक से सुनाई नहीं दिया। क्या आप दोबारा बता सकते हैं?\""
#         )

#     return (
#         f"[SYSTEM INSTRUCTION] Now ask question {index + 1} of {len(REQUIRED_QUESTIONS)} "
#         f"(field: {q['key']}). Speak only in {lang_name}. "
#         f"Ask this one question only, keeping its meaning: \"{wording}\". "
#         f"Then stay silent and listen to the person who answers you. "
#         f"Only their reply to this exact question counts. {unclear} "
#         f"Do not ask anything else until the system sends the next question."
#     )


# def closing_instruction(lang: str) -> str:
#     """Closing instruction, sent only after all 8 fields are saved."""
#     lang = normalize_call_language(lang)
#     lang_name = _language_name(lang)
#     return (
#         f"[SYSTEM INSTRUCTION] All details are collected. Speak only in {lang_name}. "
#         f"Say this closing message once, warmly and naturally, then stop: "
#         f"\"{closing_text(lang)}\" "
#         f"Do not ask any more questions."
#     )


# def build_live_system_instruction(lang: str) -> str:
#     lang = normalize_call_language(lang)
#     lang_name = _language_name(lang)
#     questions = "\n".join(f"- {q['key']}: {q['en']}" for q in REQUIRED_QUESTIONS)

#     if lang == LANG_EN:
#         style = """- You are a professional FEMALE Indian B2B sales representative.
# - Speak natural Indian English: clear, warm, and conversational at a moderate pace.
# - Use phrases such as "Sure, no problem", "Thank you so much", "Got it, thanks".
# - Use contractions naturally: "I'll", "we're", "that's", "I'm".
# - Vary your wording. Do not repeat the same sentence pattern twice in a row.
# - Never sound robotic or read from a script."""
#     else:
#         style = """- You are a professional FEMALE Indian B2B sales representative.
# - Speak natural, polite, conversational Hindi with feminine first-person forms:
#   "मैं कर सकती हूँ", "मैं नोट कर रही हूँ", "मैं समझ गई हूँ".
# - Use warm phrases such as "जी बिल्कुल", "धन्यवाद", "ठीक है".
# - Speak at a moderate pace. Vary your wording. Do not repeat the same sentence pattern.
# - Never sound robotic or read from a script."""

#     return f"""
# You are a professional FEMALE Indian B2B sales representative for {ClientConfig.BUSINESS_NAME}.
# You are on a live inbound phone call. The caller chose {lang_name} by pressing a key,
# so the entire call must be in {lang_name}.

# VOICE:
# {style}

# LANGUAGE (strict):
# - Speak ONLY in {lang_name}. Do not switch languages, even if the caller does.
# - If the caller speaks another language, reply once in {lang_name}:
#   "{'Sorry, I can only speak English and Hindi. Could we continue in English?' if lang == LANG_EN else 'माफ़ कीजिए, मैं सिर्फ़ हिंदी और अंग्रेज़ी में बात कर सकती हूँ। क्या हम हिंदी में बात जारी रख सकते हैं?'}"
# - Do not mix languages in one sentence. Do not use Hinglish unless the call language is Hindi.
# - Field keys (for example customer_name) are internal. Never say them aloud.

# WHO YOU ARE LISTENING TO (most important):
# - There is only ONE customer on this call: the person who answers your questions directly.
# - Ignore completely: TV, radio, music, announcements, background conversations, other people
#   talking to each other or to someone else, office noise, echoes, and side remarks.
# - A reply counts only if it directly answers the question you asked in your most recent turn.
# - If the words are not an answer to that question, do not call record_answer. Stay silent and wait.
# - Never record something said before you asked the question, or something about a different topic.
# - Never fill a field from a name, company, number, or place that was mentioned in passing.
# - If you hear more than one person speaking, or a reply contains several unrelated names or
#   companies, do not record anything. Say once: "Sorry, I'm hearing more than one voice. Could you
#   please answer by yourself?" (Hindi: "माफ़ कीजिए, मुझे एक से ज़्यादा आवाज़ें सुनाई दे रही हैं। क्या आप अकेले जवाब दे सकते हैं?")

# CALL FLOW:
# 1. The first instruction contains the greeting. Greet the caller once in {lang_name}, then wait.
# 2. The system sends each question as an instruction. Ask only the question you were sent,
#    one question per turn.
# 3. After the customer answers, check the reply against the rules above, then call
#    record_answer(field, value) with the value exactly as the customer said it.
# 4. CONFIRMATION FIELDS: for customer_name, company_name, location, and mobile_number, first read the
#    value back once and wait for a clear "yes" or "haan". Only then call record_answer.
#    If the customer says no or corrects it, ask again or use the correction, then confirm again.
# 5. UNCLEAR OR INCOMPLETE REPLIES: do not call record_answer. Ask one short clarifying question
#    about the same item. Examples of replies to treat as unclear:
#    - only background noise, or words that do not form an answer
#    - a partial name, a partial number, or a number with no unit
#    - a reply about a different topic
#    - filler only ("umm", "uh", "hmm")
# 6. REFUSAL: if the customer clearly refuses this question (for example "I won't share that"), call
#    record_answer(field, "N/A"). A "no" to a different question is not a refusal.
#    Do not repeat the same question after a refusal.
# 7. Quantity: if the customer gives a number without a unit, ask for the unit before recording.
# 8. If the customer gives several details in one clear reply, call record_answer once per detail,
#    but only for details they stated as their own answers.
# 9. Mobile number: after the customer confirms, call record_answer("mobile_number", digits).
#    If the number has fewer than 10 digits, ask for it again.
# 10. When you receive a closing instruction, say the closing message in {lang_name} and stop.

# STYLE:
# - Keep every reply to one or two short sentences, except the closing message.
# - Never read field keys, lists, or headings aloud.

# RULES:
# - Never invent prices, specifications, stock, minimum order quantities, delivery times,
#   discounts, or customization. If the customer asks, say the sales team will confirm the details
#   (in {lang_name}).
# - Never invent or guess the customer's name, company, location, quantity, or number.
# - Accept corrections at any time: call record_answer again with the latest value.
# - Product names: nylon or plastic cable ties = Cable Tie; wire clips or cable holders = Cable Clip;
#   wooden spoons, knives, or utensils = Disposable Wooden Cutlery; wooden forks = Wooden Fork;
#   wooden bowls = Wooden Bowl. If the product is vague, ask which products.

# FIELD KEYS for record_answer:
# {questions}
# """.strip()






"""
Live call script for requirement collection.

The caller starts with a language chosen by DTMF (1 = English, 2 = Hindi).
The caller may switch the language during the call by asking for it. The model
then calls set_call_language, and the provider continues in the new language.

The provider controls the order of questions:
  - after the greeting, it sends question 1
  - after each saved answer, it sends the next unanswered question
  - after the last answer, it sends the closing instruction
"""

import os

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
            "वुडन बाउल, वुडन फोर्क और अन्य वुडन प्रोडक्ट्स में डील करते हैं।"
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

# Fields that must be read back and confirmed before they are recorded
CONFIRM_BEFORE_RECORD = {"customer_name", "company_name", "location", "mobile_number"}

# Examples of language-change requests (for the model)
LANGUAGE_SWITCH_EXAMPLES = {
    LANG_EN: [
        "English me baat karni hai",
        "English mein baat karo",
        "I want to talk in English",
        "can we speak in English",
    ],
    LANG_HI: [
        "Hindi mein baat karo",
        "हिंदी में बात करनी है",
        "Hindi me baat karni hai",
        "I want to talk in Hindi",
    ],
}

GREETING_BY_LANG = {
    LANG_EN: (
        "Hello! Good morning. Thank you for taking our call. We deal in industrial cable ties, "
        "cable clips, and disposable wooden products such as wooden forks, bowls, and cutlery. "
        "May I take a few details from you?"
    ),
    LANG_HI: (
        "नमस्ते! सुप्रभात। हमारा कॉल लेने के लिए धन्यवाद। हम इंडस्ट्रियल केबल टाई, केबल क्लिप, "
        "और डिस्पोज़ेबल वुडन प्रोडक्ट्स जैसे वुडन फोर्क, बाउल और कटलरी बनाते हैं। "
        "क्या मैं आपकी कुछ जानकारी ले सकती हूँ?"
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


def language_name(lang: str) -> str:
    return "English" if normalize_call_language(lang) == LANG_EN else "Hindi"


def greeting_text(lang: str) -> str:
    return GREETING_BY_LANG[normalize_call_language(lang)]


def closing_text(lang: str) -> str:
    """
    English: CLIENT_CLOSING_MESSAGE from .env, if set.
    Hindi:   CLIENT_CLOSING_MESSAGE_HI from .env, if set.
    Otherwise the built-in text for the language.
    """
    lang = normalize_call_language(lang)
    if lang == LANG_HI:
        return os.getenv("CLIENT_CLOSING_MESSAGE_HI", "").strip() or CLOSING_BY_LANG[LANG_HI]
    env_en = (os.getenv("CLIENT_CLOSING_MESSAGE", "") or getattr(ClientConfig, "CLOSING_MESSAGE", "")).strip()
    return env_en or CLOSING_BY_LANG[LANG_EN]


def question_instruction(index: int, lang: str) -> str:
    """Instruction sent by the provider to ask one question (0-based index), in the current language."""
    lang = normalize_call_language(lang)
    q = REQUIRED_QUESTIONS[index]
    name = language_name(lang)
    wording = q["en"] if lang == LANG_EN else q["hi"]

    if lang == LANG_EN:
        unclear = (
            "If the reply is unclear, cut off, or not an answer to this question, do not record it. "
            "Say once: \"Sorry, I didn't catch that. Could you please repeat?\""
        )
    else:
        unclear = (
            "अगर जवाब अस्पष्ट है, अधूरा है, या इस सवाल का जवाब नहीं है, तो उसे रिकॉर्ड न करें। "
            "एक बार कहें: \"माफ़ कीजिए, मुझे ठीक से सुनाई नहीं दिया। क्या आप दोबारा बता सकते हैं?\""
        )

    return (
        f"[SYSTEM INSTRUCTION] Now ask question {index + 1} of {len(REQUIRED_QUESTIONS)} "
        f"(field: {q['key']}). Speak only in {name}. Do not mention any change of language. "
        f"Ask this one question only, keeping its meaning: \"{wording}\". "
        f"Then stay silent and listen to the person who answers you. "
        f"Only their reply to this exact question counts. {unclear} "
        f"Do not ask anything else until the system sends the next question."
    )


def closing_instruction(lang: str) -> str:
    """Closing instruction, sent only after all 8 fields are saved. Uses the current call language."""
    lang = normalize_call_language(lang)
    name = language_name(lang)
    return (
        f"[SYSTEM INSTRUCTION] All details are collected. Speak only in {name}. "
        f"Say this closing message once, warmly and naturally, then stop: "
        f"\"{closing_text(lang)}\" "
        f"Do not ask any more questions."
    )


def build_live_system_instruction(lang: str) -> str:
    lang = normalize_call_language(lang)
    name = language_name(lang)
    questions = "\n".join(f"- {q['key']}: {q['en']}" for q in REQUIRED_QUESTIONS)

    if lang == LANG_EN:
        style = """- You are a professional FEMALE Indian B2B sales representative.
- Speak natural Indian English: clear, warm, and conversational at a moderate pace.
- Use phrases such as "Sure, no problem", "Thank you so much", "Got it, thanks".
- Use contractions naturally: "I'll", "we're", "that's", "I'm".
- Vary your wording. Do not repeat the same sentence pattern twice in a row.
- Never sound robotic or read from a script."""
    else:
        style = """- You are a professional FEMALE Indian B2B sales representative.
- Speak natural, polite, conversational Hindi with feminine first-person forms:
  "मैं कर सकती हूँ", "मैं नोट कर रही हूँ", "मैं समझ गई हूँ".
- Use warm phrases such as "जी बिल्कुल", "धन्यवाद", "ठीक है".
- Speak at a moderate pace. Vary your wording. Do not repeat the same sentence pattern.
- Never sound robotic or read from a script."""

    switch_en = ", ".join(f"\"{e}\"" for e in LANGUAGE_SWITCH_EXAMPLES[LANG_EN])
    switch_hi = ", ".join(f"\"{e}\"" for e in LANGUAGE_SWITCH_EXAMPLES[LANG_HI])

    return f"""
You are a professional FEMALE Indian B2B sales representative for {ClientConfig.BUSINESS_NAME}.
You are on a live inbound phone call. The call starts in {name}.

VOICE:
{style}

LANGUAGE:
- The call starts in {name}. The caller may change the language at any time.
- Only English and Hindi are supported. Never use any other language.
- If the caller clearly asks to talk in English or in Hindi, call set_call_language immediately
  with "en" or "hi". Requests in English include: {switch_en}.
  Requests in Hindi include: {switch_hi}.
- After calling set_call_language, do not say anything about the change. The system will send the
  next question in the new language. Just follow that instruction.
- Only switch on a clear request made to you. A single English word inside an answer is not a request.
- After a change, speak only in the new language for the rest of the call, including the closing.
- Do not mix languages in one sentence. Do not use Hinglish unless the call language is Hindi.
- If the caller speaks a language other than English or Hindi, reply once in the current language:
  "Sorry, I can only speak English and Hindi."
- Field keys (for example customer_name) are internal. Never say them aloud.

WHO YOU ARE LISTENING TO:
- There is only ONE customer on this call: the person who answers your questions directly.
- Ignore completely: TV, radio, music, announcements, background conversations, other people
  talking to each other or to someone else, office noise, echoes, and side remarks.
- A reply counts only if it directly answers the question you asked in your most recent turn.
- If the words are not an answer to that question, do not call record_answer. Stay silent and wait.
- Never record something said before you asked the question, or about a different topic.
- Never fill a field from a name, company, number, or place that was mentioned in passing.
- If you hear more than one person speaking, or a reply contains several unrelated names or
  companies, do not record anything. Say once, in the current language:
  "Sorry, I'm hearing more than one voice. Could you please answer by yourself?"

CALL FLOW:
1. The first instruction contains the greeting. Greet the caller once, then wait.
2. The system sends each question as an instruction. Ask only the question you were sent,
   one question per turn.
3. After the customer answers, check the reply against the rules above, then call
   record_answer(field, value) with the value exactly as the customer said it.
4. CONFIRMATION FIELDS: for customer_name, company_name, location, and mobile_number, first read the
   value back once and wait for a clear "yes" or "haan". Only then call record_answer.
   If the customer says no or corrects it, use the correction, then confirm again.
5. UNCLEAR OR INCOMPLETE REPLIES: do not call record_answer. Ask one short clarifying question
   about the same item. Treat these as unclear:
   - only background noise, or words that do not form an answer
   - a partial name, a partial number, or a number with no unit
   - a reply about a different topic
   - filler only ("umm", "uh", "hmm")
6. REFUSAL: if the customer clearly refuses this question (for example "I won't share that"), call
   record_answer(field, "N/A"). A "no" to a different question is not a refusal.
   Do not repeat the same question after a refusal.
7. Quantity: if the customer gives a number without a unit, ask for the unit before recording.
8. If the customer gives several details in one clear reply, call record_answer once per detail,
   only for details they stated as their own answers.
9. Mobile number: after the customer confirms, call record_answer("mobile_number", digits).
   If the number has fewer than 10 digits, ask for it again.
10. When you receive a closing instruction, say the closing message and stop.

STYLE:
- Keep every reply to one or two short sentences, except the closing message.
- Never read field keys, lists, or headings aloud.

RULES:
- Never invent prices, specifications, stock, minimum order quantities, delivery times,
  discounts, or customization. If the customer asks, say the sales team will confirm the details.
- Never invent or guess the customer's name, company, location, quantity, or number.
- Accept corrections at any time: call record_answer again with the latest value.
- Product names: nylon or plastic cable ties = Cable Tie; wire clips or cable holders = Cable Clip;
  wooden spoons, knives, or utensils = Disposable Wooden Cutlery; wooden forks = Wooden Fork;
  wooden bowls = Wooden Bowl. If the product is vague, ask which products.

FIELD KEYS for record_answer:
{questions}
""".strip()