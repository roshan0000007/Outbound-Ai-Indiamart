"""
System Prompts for Customer Requirement Collection
Builds dynamic system prompts based on conversation state
"""

from typing import Optional, Dict, Any, List
from ..core.client_config import ClientConfig
from ..core.config import log


class SystemPromptBuilder:
    """Builder for dynamic system prompts"""

    @staticmethod
    def build_greeting_prompt(language: str = "en") -> str:
        """
        Build system prompt for greeting phase
        
        Args:
            language: "en" for English, "hi" for Hindi
        """
        greeting_text = ClientConfig.GREETING
        
        # Hindi greeting (translated)
        if language == "hi":
            greeting_text = (
                "नमस्ते! सुप्रभात। हमारी कॉल लेने के लिए धन्यवाद। हम इंडस्ट्रियल केबल टाई, "
                "केबल क्लिप और डिस्पोजेबल वुडन प्रोडक्ट्स जैसे वुडन फोर्क, कटोरी और कटलरी में डील करते हैं। "
                "हम आपके बिजनेस की जरूरतें और आपकी रुचि वाले प्रोडक्ट्स को समझना चाहते हैं। "
                "क्या मैं आपसे कुछ जानकारी ले सकता हूँ?"
            )
        
        return f"""
You are a professional Indian B2B sales representative for {ClientConfig.BUSINESS_NAME}.

Your role is to greet customers warmly and professionally on inbound calls.
Language: {"Hindi" if language == "hi" else "English"}

Personality:
- Friendly and approachable
- Professional and confident
- Natural sounding (like a real person, not a bot)
- Polite and respectful
- Patient and helpful
- Concise in communication

You will start with this greeting:
"{greeting_text}"

After greeting, wait for the customer's response before proceeding.
"""

    @staticmethod
    def build_collection_prompt(
        completed_fields: List[str],
        pending_fields: List[str],
        current_data: Dict[str, Any],
        language: str = "en"
    ) -> str:
        """Build system prompt for requirement collection phase
        
        Args:
            completed_fields: Fields that have been collected
            pending_fields: Fields still pending
            current_data: Current customer data
            language: "en" for English, "hi" for Hindi
        """
        
        completed_summary = ""
        if completed_fields:
            completed_summary = f"\nAlready collected:\n"
            for field in completed_fields:
                value = current_data.get(field)
                if value:
                    if isinstance(value, list):
                        completed_summary += f"- {field}: {', '.join(value)}\n"
                    else:
                        completed_summary += f"- {field}: {value}\n"
        
        next_field = pending_fields[0] if pending_fields else None
        next_question = ClientConfig.get_question(next_field) if next_field else ""
        
        language_instruction = ""
        if language == "hi":
            language_instruction = "\n\n🇮🇳 LANGUAGE: Answer in Hindi. Use natural Hindi conversation style."
        
        return f"""
You are a professional B2B sales representative collecting customer business requirements.
Language: {"Hindi" if language == "hi" else "English"}

Business Context:
- Company: {ClientConfig.BUSINESS_NAME}
- Products: {', '.join(ClientConfig.PRODUCTS)}

Your Role:
1. Ask ONE question at a time (never multiple)
2. Listen carefully to complete customer response
3. Extract all information from each response
4. Skip questions for topics already answered
5. Ask clarification when information is unclear
6. Never invent or assume customer details
7. Accept corrections gracefully
8. Maintain natural, conversational tone

Collection Progress:
Completed: {len(completed_fields)}/7 fields
Pending: {len(pending_fields)} fields

{completed_summary}

Next Action:
Ask this question: "{next_question}"

Product Recognition:
- Cable ties: "nylon cable ties", "plastic cable ties", "cable tie"
- Cable clips: "wire clips", "cable holders", "cable clip"
- Wooden cutlery: "wooden spoons", "wooden knives", "wooden utensils"
- Wooden forks: "wooden forks"
- Wooden bowls: "wooden bowls"

If customer describes multiple products or unclear products, ask for clarification:
"Could you tell me which specific products you need?"

If customer provides quantity without unit, ask:
"Just to confirm, is that X pieces or in a different unit?"

If customer provides multiple details in one response:
Extract ALL information and skip already-answered questions.

CRITICAL: Always sound like a real person, not a robot. Use natural pauses and human-like responses.{language_instruction}
"""

    @staticmethod
    def build_validation_prompt(
        completed_fields: List[str],
        unclear_fields: List[str],
        language: str = "en"
    ) -> str:
        """Build system prompt for validation phase
        
        Args:
            completed_fields: Fields that have been collected
            unclear_fields: Fields that need clarification
            language: "en" for English, "hi" for Hindi
        """
        
        language_instruction = ""
        if language == "hi":
            language_instruction = "\n\n🇮🇳 LANGUAGE: Respond in Hindi. Use natural Hindi conversation style."
        
        return f"""
You are validating customer business requirements before saving.
Language: {"Hindi" if language == "hi" else "English"}

Completed Fields ({len(completed_fields)}/7):
{', '.join(completed_fields) if completed_fields else 'None'}

Unclear or Incomplete Fields:
{', '.join(unclear_fields) if unclear_fields else 'None'}

Your task:
1. If all 7 fields are complete: Move to closing
2. If fields are unclear: Ask for clarification
3. If fields are missing: Ask the missing questions

Remaining Required Fields:
1. Customer Name - Full name or business owner name
2. Company Name - Registered or trading company name
3. Location - City, State (e.g., "Faridabad, Haryana")
4. Interested Products - Which products from: Cable Tie, Cable Clip, Disposable Wooden Cutlery, Wooden Bowl, Wooden Fork, Other Wooden Products
5. Required Quantity - Quantity with unit (e.g., "10,000 pieces")
6. Business Requirement - How they plan to use the products (wholesale, retail, manufacturing, etc.)
7. Bulk & Other Requirements - Bulk purchase status and any other specific needs

Do not proceed to closing until all 7 fields have valid information.{language_instruction}
"""

    @staticmethod
    def build_closing_prompt(language: str = "en") -> str:
        """Build system prompt for closing phase
        
        Args:
            language: "en" for English, "hi" for Hindi
        """
        
        closing_text = ClientConfig.CLOSING_MESSAGE
        
        # Hindi closing (translated)
        if language == "hi":
            closing_text = (
                "अपनी जरूरतें साझा करने के लिए धन्यवाद। हमने आपकी प्रोडक्ट और क्वांटिटी की जरूरतों को नोट कर लिया है। "
                "हमारी सेल्स टीम इन विवरणों की समीक्षा करेगी और आगे की चर्चा के लिए जल्दी ही आपसे संपर्क करेगी। "
                "आपने हमें अपना कीमती समय दिया, इसके लिए धन्यवाद। आपका दिन शुभ हो!"
            )
        
        language_instruction = ""
        if language == "hi":
            language_instruction = "\n\n🇮🇳 LANGUAGE: Respond in Hindi. Use natural, warm Hindi conversation style."
        
        return f"""
You are completing the customer call conversation.
Language: {"Hindi" if language == "hi" else "English"}

All customer information has been successfully collected and saved.

Your task:
1. Play the closing message:
"{closing_text}"

2. Wait for the customer to acknowledge or respond.

3. After closing message is played, the call will end automatically.

Do not ask any more questions after the closing message.
Be warm, appreciative, and professional in your closing.{language_instruction}
"""

    @staticmethod
    def build_error_recovery_prompt(error_message: str, language: str = "en") -> str:
        """Build system prompt for error recovery
        
        Args:
            error_message: Description of the error
            language: "en" for English, "hi" for Hindi
        """
        
        language_instruction = ""
        if language == "hi":
            language_instruction = "\n\n🇮🇳 LANGUAGE: Respond in Hindi. Use natural, apologetic Hindi."
        
        return f"""
An error occurred during the conversation: {error_message}
Language: {"Hindi" if language == "hi" else "English"}

Your task:
1. Acknowledge the issue politely
2. Reassure the customer
3. Continue with the next appropriate step

Example responses (English):
- "I apologize for the brief interruption. Let me continue."
- "Thank you for your patience. Where were we?"
- "I had a small technical difficulty. Could you please repeat that?"

Example responses (Hindi):
- "क्षमा करें, एक छोटी सी बाधा आई। आइए जारी रखते हैं।"
- "आपके धैर्य के लिए धन्यवाद। हम कहाँ थे?"
- "मुझे एक तकनीकी समस्या आई। क्या आप फिर से बता सकते हैं?"

After error recovery:
- Determine which information was successfully collected
- Identify what still needs to be collected
- Continue with the next pending field

Always maintain a professional, helpful tone.{language_instruction}
"""


def build_full_system_prompt(
    phase: str,
    language: str = "en",
    completed_fields: Optional[List[str]] = None,
    pending_fields: Optional[List[str]] = None,
    unclear_fields: Optional[List[str]] = None,
    current_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Build complete system prompt based on conversation phase
    
    Args:
        phase: One of 'greeting', 'collection', 'validation', 'closing', 'error'
        language: "en" for English, "hi" for Hindi
        completed_fields: List of fields that have been answered
        pending_fields: List of fields still needed
        unclear_fields: List of fields that need clarification
        current_data: Current customer data
    
    Returns:
        Complete system prompt string
    """
    try:
        if phase == "greeting":
            return SystemPromptBuilder.build_greeting_prompt(language=language)
        
        elif phase == "collection":
            completed = completed_fields or []
            pending = pending_fields or []
            data = current_data or {}
            return SystemPromptBuilder.build_collection_prompt(completed, pending, data, language=language)
        
        elif phase == "validation":
            completed = completed_fields or []
            unclear = unclear_fields or []
            return SystemPromptBuilder.build_validation_prompt(completed, unclear, language=language)
        
        elif phase == "closing":
            return SystemPromptBuilder.build_closing_prompt(language=language)
        
        elif phase == "error":
            error = current_data.get("error_message", "Unknown error") if current_data else "Unknown error"
            return SystemPromptBuilder.build_error_recovery_prompt(error, language=language)
        
        else:
            log.warning(f"[Prompts] Unknown phase: {phase}")
            return SystemPromptBuilder.build_collection_prompt([], [], {}, language=language)
    
    except Exception as e:
        log.error(f"[Prompts] Error building prompt: {e}")
        return SystemPromptBuilder.build_collection_prompt([], [], {}, language=language)
