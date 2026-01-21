"""
Gemini LLM Adapter - Implements LLMPort for Google Gemini.
"""

import asyncio
import json
from typing import Any, Optional

from google import genai
from google.genai import types

from src.domain.ports.llm_port import LLMMessage, LLMPort, LLMResponse
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_RETRY_DELAY = 2.0  # seconds
RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504]


class GeminiAdapter(LLMPort):
    """
    Google Gemini implementation of LLMPort.
    
    Uses the google-genai SDK for API access.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize Gemini adapter.
        
        Args:
            settings: Application settings with API key.
        """
        self.settings = settings
        self._model_name = settings.gemini_model
        
        # Initialize the client
        self._client = genai.Client(api_key=settings.gemini_api_key)
        
        logger.info("Gemini adapter initialized", model=self._model_name)
    
    @property
    def model_name(self) -> str:
        """Get the model name being used."""
        return self._model_name
    
    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if an error is retryable."""
        error_str = str(error).lower()
        # Check for common retryable status codes in error message
        if any(str(code) in error_str for code in RETRYABLE_STATUS_CODES):
            return True
        # Check for common retryable keywords
        retryable_keywords = ["overloaded", "unavailable", "rate limit", "too many requests", "timeout"]
        return any(keyword in error_str for keyword in retryable_keywords)
    
    async def _generate_with_retry(
        self,
        contents: list,
        config: types.GenerateContentConfig,
    ) -> Any:
        """Generate content with retry logic for transient errors."""
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model_name,
                    contents=contents,
                    config=config,
                )
                return response
            except Exception as e:
                last_error = e
                if self._is_retryable_error(e) and attempt < MAX_RETRIES - 1:
                    delay = BASE_RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        "Gemini API error, retrying",
                        attempt=attempt + 1,
                        max_retries=MAX_RETRIES,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
        
        raise last_error  # Should not reach here, but just in case
    
    async def generate(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a response from Gemini."""
        logger.debug("Generating response", model=self._model_name, message_count=len(messages))
        
        # Build conversation content
        contents = []
        system_instruction = None
        
        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            elif msg.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=msg.content)]))
            elif msg.role == "assistant":
                contents.append(types.Content(role="model", parts=[types.Part(text=msg.content)]))
        
        # Configure generation
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_instruction,
        )
        
        if json_mode:
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                system_instruction=system_instruction,
                response_mime_type="application/json",
            )
        
        # Generate response with retry logic
        response = await self._generate_with_retry(
            contents=contents,
            config=config,
        )
        
        # Extract usage info
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = {
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0),
            }
        
        finish_reason = "stop"
        if response.candidates and response.candidates[0].finish_reason:
            finish_reason = str(response.candidates[0].finish_reason).lower()
        
        # Check for empty/blocked responses
        content = response.text if response.text is not None else ""
        if not content:
            logger.warning("Gemini returned empty response", finish_reason=finish_reason)
        
        return LLMResponse(
            content=content,
            model=self._model_name,
            usage=usage,
            finish_reason=finish_reason,
            raw_response=response,
        )
    
    async def generate_with_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a response with system and user prompts."""
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]
        return await self.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
    
    async def generate_structured(
        self,
        messages: list[LLMMessage],
        output_schema: dict[str, Any],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Generate a structured response matching a schema."""
        # Append schema instruction to the last user message
        schema_instruction = (
            f"\n\nRespond ONLY with valid JSON matching this schema:\n"
            f"```json\n{json.dumps(output_schema, indent=2)}\n```"
        )
        
        modified_messages = messages.copy()
        if modified_messages and modified_messages[-1].role == "user":
            modified_messages[-1] = LLMMessage(
                role="user",
                content=modified_messages[-1].content + schema_instruction,
            )
        
        response = await self.generate(
            messages=modified_messages,
            temperature=temperature,
            json_mode=True,
        )
        
        # Parse JSON response
        if not response.content:
            logger.error("Empty response from Gemini", finish_reason=response.finish_reason)
            raise ValueError("Gemini returned empty response - likely blocked by safety filters")
        
        try:
            return json.loads(response.content)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse JSON response", error=str(e), content=response.content)
            # Try to extract JSON from response
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content.strip())
    
    async def health_check(self) -> bool:
        """Check if Gemini service is available."""
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents="Hello",
            )
            return response.text is not None
        except Exception as e:
            logger.error("Gemini health check failed", error=str(e))
            return False
