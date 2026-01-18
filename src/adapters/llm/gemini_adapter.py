"""
Gemini LLM Adapter - Implements LLMPort for Google Gemini.
"""

import json
from typing import Any, Optional

from google import genai
from google.genai import types

from src.domain.ports.llm_port import LLMMessage, LLMPort, LLMResponse
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


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
        
        # Generate response
        response = await self._client.aio.models.generate_content(
            model=self._model_name,
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
        
        return LLMResponse(
            content=response.text,
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
