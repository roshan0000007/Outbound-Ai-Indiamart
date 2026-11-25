"""
Base LLM Provider Interface
Abstract base class for LLM providers
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

class BaseLLMProvider(ABC):
    """Base class for LLM providers"""

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the LLM provider"""
        pass

    @abstractmethod
    async def generate(self, prompt: str, temperature: float = 0.7,
                      max_tokens: int = 150) -> Optional[str]:
        """Generate text response"""
        pass

    @abstractmethod
    async def generate_with_history(self, messages: List[Dict], temperature: float = 0.7,
                                    max_tokens: int = 150, system_prompt: Optional[str] = None,
                                    language: Optional[str] = None) -> Optional[str]:
        """Generate response with conversation history"""
        pass

    @abstractmethod
    async def close(self):
        """Close the provider connection"""
        pass
