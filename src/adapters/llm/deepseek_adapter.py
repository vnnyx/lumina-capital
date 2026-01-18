"""
DeepSeek LLM Adapter - Implements LLMPort for DeepSeek R1.
"""

import json
from typing import Any, Optional

from openai import AsyncOpenAI

from src.domain.ports.llm_port import LLMMessage, LLMPort, LLMResponse
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class DeepSeekAdapter(LLMPort):
    """
    DeepSeek implementation of LLMPort.
    
    Uses OpenAI-compatible API via the openai SDK.
    DeepSeek R1 is a reasoning model optimized for analysis and decision-making.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize DeepSeek adapter.
        
        Args:
            settings: Application settings with API key.
        """
        self.settings = settings
        self._model_name = settings.deepseek_model
        
        # Initialize OpenAI client with DeepSeek base URL
        self._client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        
        logger.info("DeepSeek adapter initialized", model=self._model_name)
    
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
        """Generate a response from DeepSeek."""
        logger.debug("Generating response", model=self._model_name, message_count=len(messages))
        
        # Convert messages to OpenAI format
        openai_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
        
        # Build request parameters
        params: dict[str, Any] = {
            "model": self._model_name,
            "messages": openai_messages,
            "temperature": temperature,
        }
        
        if max_tokens:
            params["max_tokens"] = max_tokens
        
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        
        # Make API request
        response = await self._client.chat.completions.create(**params)
        
        # Extract response content
        choice = response.choices[0]
        content = choice.message.content or ""
        
        # Extract reasoning content if present (DeepSeek R1 specific)
        reasoning_content = ""
        if hasattr(choice.message, "reasoning_content"):
            reasoning_content = choice.message.reasoning_content or ""
            logger.debug("Reasoning content received", length=len(reasoning_content))
        
        # Combine reasoning and content for full response
        full_content = content
        if reasoning_content and not json_mode:
            full_content = f"<reasoning>\n{reasoning_content}\n</reasoning>\n\n{content}"
        
        # Build usage dict
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            # Add reasoning tokens if available
            if hasattr(response.usage, "completion_tokens_details"):
                details = response.usage.completion_tokens_details
                if hasattr(details, "reasoning_tokens"):
                    usage["reasoning_tokens"] = details.reasoning_tokens
        
        return LLMResponse(
            content=full_content,
            model=self._model_name,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
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
            f"\n\nYou MUST respond ONLY with valid JSON matching this exact schema. "
            f"Do not include any other text, markdown formatting, or explanation outside the JSON:\n"
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
        content = response.content
        
        # Remove reasoning tags if present
        if "<reasoning>" in content:
            # Extract content after reasoning
            parts = content.split("</reasoning>")
            if len(parts) > 1:
                content = parts[-1].strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse JSON response", error=str(e), content=content[:500])
            
            # Try to extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            elif "{" in content:
                # Find the JSON object
                start = content.index("{")
                # Find matching closing brace
                depth = 0
                end = start
                for i, c in enumerate(content[start:], start):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                content = content[start:end]
            
            return json.loads(content.strip())
    
    async def health_check(self) -> bool:
        """Check if DeepSeek service is available."""
        try:
            response = await self._client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10,
            )
            return response.choices[0].message.content is not None
        except Exception as e:
            logger.error("DeepSeek health check failed", error=str(e))
            return False
