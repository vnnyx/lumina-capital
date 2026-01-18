"""
LLM Port - Interface for Large Language Model operations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class LLMMessage:
    """Represents a message in an LLM conversation."""
    
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM."""
    
    content: str
    model: str
    usage: dict[str, int]  # tokens used
    finish_reason: str
    raw_response: Optional[Any] = None


class LLMPort(ABC):
    """
    Port interface for LLM operations.
    
    Implementations:
        - GeminiAdapter: Google Gemini API
        - DeepSeekAdapter: DeepSeek API
    """
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get the model name being used."""
        ...
    
    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """
        Generate a response from the LLM.
        
        Args:
            messages: Conversation history
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens in response
            json_mode: If True, expect JSON output
            
        Returns:
            LLMResponse with generated content.
        """
        ...
    
    @abstractmethod
    async def generate_with_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """
        Generate a response with system and user prompts.
        
        Convenience method that constructs messages internally.
        
        Args:
            system_prompt: System/persona instructions
            user_prompt: User query or task
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            json_mode: If True, expect JSON output
            
        Returns:
            LLMResponse with generated content.
        """
        ...
    
    @abstractmethod
    async def generate_structured(
        self,
        messages: list[LLMMessage],
        output_schema: dict[str, Any],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """
        Generate a structured response matching a schema.
        
        Args:
            messages: Conversation history
            output_schema: JSON schema for expected output
            temperature: Sampling temperature (lower for structured)
            
        Returns:
            Parsed dictionary matching the schema.
        """
        ...
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the LLM service is available.
        
        Returns:
            True if service is healthy.
        """
        ...
