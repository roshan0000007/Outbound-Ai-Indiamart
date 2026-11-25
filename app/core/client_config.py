"""
Client Configuration
Loads and manages client-specific configuration
"""

import os
from typing import Optional, Dict, List
from dotenv import load_dotenv
from . config import log

load_dotenv()


class ClientConfig:
    """Client-specific configuration"""

    # Business Information
    BUSINESS_NAME = os.getenv("CLIENT_BUSINESS_NAME", "Industrial Products & Disposable Wooden Products")
    
    # Default Language
    DEFAULT_LANGUAGE = os.getenv("CLIENT_DEFAULT_LANGUAGE", "en-IN")
    
    # Greeting Configuration
    DEFAULT_GREETING = (
        "Hello! Good morning. Thank you for taking our call. We deal in industrial cable ties, "
        "cable clips, and disposable wooden products such as wooden forks, bowls, and cutlery. "
        "We would like to understand your business requirements and the products you may be interested in. "
        "May I take a few details from you?"
    )
    GREETING = os.getenv("CLIENT_GREETING", DEFAULT_GREETING)
    
    # Closing Message Configuration
    DEFAULT_CLOSING_MESSAGE = (
        "Thank you for sharing your requirements with us. We have noted your product and quantity requirements. "
        "Our sales team will review the details and contact you shortly for further discussion. "
        "Thank you for your valuable time. Have a great day!"
    )
    CLOSING_MESSAGE = os.getenv("CLIENT_CLOSING_MESSAGE", DEFAULT_CLOSING_MESSAGE)
    
    # Supported Products
    PRODUCTS = [
        "Cable Tie",
        "Cable Clip",
        "Disposable Wooden Cutlery",
        "Wooden Bowl",
        "Wooden Fork",
        "Other Wooden Products"
    ]
    
    # Product Aliases
    PRODUCT_ALIASES = {
        "cable tie": ["nylon cable tie", "plastic cable tie", "cable tie", "tie"],
        "cable clip": ["wire clip", "cable holder", "cable clip", "clip"],
        "disposable wooden cutlery": ["wooden spoon", "wooden knife", "wooden cutlery", "wooden utensil", "wooden tableware"],
        "wooden fork": ["wooden fork", "fork"],
        "wooden bowl": ["wooden bowl", "bowl"],
        "other wooden products": ["wooden product", "wooden item"]
    }
    
    # Requirement Collection Configuration
    REQUIRED_FIELDS = [
        "customer_name",
        "company_name",
        "location",
        "interested_products",
        "required_quantity",
        "business_requirement",
        "bulk_and_other_requirements"
    ]
    
    REQUIRED_FIELD_QUESTIONS = {
        "customer_name": "May I know your name, please?",
        "company_name": "Could you please share your company or business name?",
        "location": "Which city and state are you contacting us from?",
        "interested_products": (
            "Which product are you interested in purchasing? "
            "We deal in cable ties, cable clips, disposable wooden cutlery, wooden bowls, wooden forks, "
            "and other wooden products."
        ),
        "required_quantity": "What quantity would you approximately require?",
        "business_requirement": (
            "Could you briefly explain your business requirement and how you plan to use these products?"
        ),
        "bulk_and_other_requirements": (
            "Are you planning to purchase in bulk, and do you have any other specific requirements?"
        )
    }
    
    # LLM System Prompt
    SYSTEM_PROMPT = os.getenv("CLIENT_SYSTEM_PROMPT", None)
    
    @classmethod
    def get_product_aliases(cls) -> Dict[str, List[str]]:
        """Get normalized product aliases"""
        return cls.PRODUCT_ALIASES
    
    @classmethod
    def normalize_product(cls, product_name: str) -> Optional[str]:
        """
        Normalize product name to canonical form
        
        Args:
            product_name: User-provided product name
        
        Returns:
            Canonical product name or None if not recognized
        """
        if not product_name:
            return None
        
        normalized = product_name.lower().strip()
        
        for canonical, aliases in cls.PRODUCT_ALIASES.items():
            if normalized in aliases:
                return canonical.title()  # Return title case
        
        return None
    
    @classmethod
    def get_greeting(cls) -> str:
        """Get client greeting message"""
        return cls.GREETING
    
    @classmethod
    def get_closing_message(cls) -> str:
        """Get client closing message"""
        return cls.CLOSING_MESSAGE
    
    @classmethod
    def get_question(cls, field_name: str) -> Optional[str]:
        """Get question for a required field"""
        return cls.REQUIRED_FIELD_QUESTIONS.get(field_name)
    
    @classmethod
    def get_all_questions(cls) -> Dict[str, str]:
        """Get all field questions"""
        return cls.REQUIRED_FIELD_QUESTIONS.copy()
    
    @classmethod
    def log_config(cls) -> None:
        """Log configuration information"""
        log.info("[ClientConfig] ═══════════════════════════════════")
        log.info(f"[ClientConfig] Business Name: {cls.BUSINESS_NAME}")
        log.info(f"[ClientConfig] Default Language: {cls.DEFAULT_LANGUAGE}")
        log.info(f"[ClientConfig] Supported Products: {', '.join(cls.PRODUCTS)}")
        log.info(f"[ClientConfig] Required Fields: {', '.join(cls.REQUIRED_FIELDS)}")
        log.info(f"[ClientConfig] Greeting (first 50 chars): {cls.GREETING[:50]}...")
        log.info(f"[ClientConfig] Closing (first 50 chars): {cls.CLOSING_MESSAGE[:50]}...")
        log.info("[ClientConfig] ═══════════════════════════════════")


# Log configuration on import
try:
    ClientConfig.log_config()
except Exception as e:
    log.warning(f"[ClientConfig] Error logging configuration: {e}")
