"""
PrescpHealth Backend — LLM Provider Abstraction.

Pluggable interface for different LLM backends with automatic failover.

Supported Providers:
    - GPT-4o (OpenAI cloud API)
    - Claude Opus (Anthropic cloud API)
    - Ollama (local open-source models via REST API)

Failover Logic:
    Primary: GPT-4o (most capable)
    Fallback 1: Claude Opus (if GPT-4o error/timeout)
    Fallback 2: Ollama (if Claude fails, always available locally)

HIPAA Compliance:
    - Cloud providers (OpenAI, Anthropic): Patient data must be de-identified before sending
    - Local Ollama: Patient data stays on-premises, no external calls
    - Never send patient names, MRNs, or PII to any provider
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional

import structlog
import httpx

logger = structlog.get_logger(__name__)


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Defines common interface: async send(messages, context) → response
    """

    @abstractmethod
    async def send(
        self,
        messages: list[dict],
        context: Optional[dict] = None,
        timeout: int = 30,
    ) -> str:
        """
        Send messages to LLM and get response.

        Args:
            messages: List of {role: "user"|"assistant", content: "..."}
            context: Optional context dict (e.g., patient data, risk scores)
            timeout: Request timeout in seconds

        Returns:
            str: LLM response text

        Raises:
            TimeoutError: Request exceeded timeout
            LLMError: API returned error
        """
        pass

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        """Estimate token count for billing/quota."""
        pass


class GPT4oProvider(LLMProvider):
    """
    OpenAI GPT-4o provider.

    Cloud-based, most capable model. Requires API key.
    Requires de-identification before sending patient data.
    """

    def __init__(self, api_key: str):
        """
        Initialize GPT-4o provider.

        Args:
            api_key: OpenAI API key
        """
        self.api_key = api_key
        self.model = "gpt-4o"
        self.endpoint = "https://api.openai.com/v1/chat/completions"

    async def send(
        self,
        messages: list[dict],
        context: Optional[dict] = None,
        timeout: int = 30,
    ) -> str:
        """Send to GPT-4o API."""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 500,
            }

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.error(
                        "gpt4o_api_error",
                        status=resp.status_code,
                        error=resp.text[:200],
                    )
                    raise LLMError(f"GPT-4o API error: {resp.status_code}")

                data = resp.json()
                return data["choices"][0]["message"]["content"]

        except httpx.TimeoutException:
            logger.error("gpt4o_timeout", timeout=timeout)
            raise TimeoutError(f"GPT-4o request timed out after {timeout}s")
        except LLMError:
            raise
        except Exception as exc:
            logger.error("gpt4o_failed", error=str(exc))
            raise LLMError(f"GPT-4o failed: {str(exc)}")

    async def count_tokens(self, text: str) -> int:
        """Estimate GPT-4o tokens (rough: ~1 token per 4 chars)."""
        return len(text) // 4


class ClaudeProvider(LLMProvider):
    """
    Anthropic Claude Opus provider.

    Cloud-based fallback. Requires API key.
    Requires de-identification before sending patient data.
    """

    def __init__(self, api_key: str):
        """Initialize Claude provider."""
        self.api_key = api_key
        self.model = "claude-opus-4-1"
        self.endpoint = "https://api.anthropic.com/v1/messages"

    async def send(
        self,
        messages: list[dict],
        context: Optional[dict] = None,
        timeout: int = 30,
    ) -> str:
        """Send to Claude API."""
        try:
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "max_tokens": 500,
                "messages": messages,
            }

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.error(
                        "claude_api_error",
                        status=resp.status_code,
                        error=resp.text[:200],
                    )
                    raise LLMError(f"Claude API error: {resp.status_code}")

                data = resp.json()
                return data["content"][0]["text"]

        except httpx.TimeoutException:
            logger.error("claude_timeout", timeout=timeout)
            raise TimeoutError(f"Claude request timed out after {timeout}s")
        except LLMError:
            raise
        except Exception as exc:
            logger.error("claude_failed", error=str(exc))
            raise LLMError(f"Claude failed: {str(exc)}")

    async def count_tokens(self, text: str) -> int:
        """Estimate Claude tokens (~1 token per 3 chars, slightly different from OpenAI)."""
        return len(text) // 3


class OllamaProvider(LLMProvider):
    """
    Local Ollama provider (open-source models).

    Runs locally on-premises. No cloud API, patient data stays private.
    Requires Ollama running on localhost:11434.
    """

    def __init__(self, model: str = "mistral", endpoint: str = "http://localhost:11434"):
        """
        Initialize Ollama provider.

        Args:
            model: Ollama model name (default: mistral)
            endpoint: Ollama API endpoint (default: localhost:11434)
        """
        self.model = model
        self.endpoint = f"{endpoint}/api/chat"

    async def send(
        self,
        messages: list[dict],
        context: Optional[dict] = None,
        timeout: int = 30,
    ) -> str:
        """Send to local Ollama API."""
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
            }

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    self.endpoint,
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.error(
                        "ollama_api_error",
                        status=resp.status_code,
                        error=resp.text[:200],
                    )
                    raise LLMError(f"Ollama API error: {resp.status_code}")

                data = resp.json()
                return data["message"]["content"]

        except httpx.TimeoutException:
            logger.error("ollama_timeout", timeout=timeout)
            raise TimeoutError(f"Ollama request timed out after {timeout}s")
        except LLMError:
            raise
        except Exception as exc:
            logger.error("ollama_failed", error=str(exc))
            raise LLMError(f"Ollama failed: {str(exc)}")

    async def count_tokens(self, text: str) -> int:
        """Estimate Ollama tokens (~1 token per 4 chars)."""
        return len(text) // 4


class FailoverLLMProvider(LLMProvider):
    """
    Automatic failover provider.

    Tries primary (GPT-4o) → fallback1 (Claude) → fallback2 (Ollama)
    on error or timeout. Ensures availability even if cloud APIs are down.
    """

    def __init__(
        self,
        primary: Optional[LLMProvider] = None,
        fallback1: Optional[LLMProvider] = None,
        fallback2: Optional[LLMProvider] = None,
    ):
        """
        Initialize with fallback chain.

        Args:
            primary: Primary provider (GPT-4o)
            fallback1: First fallback (Claude)
            fallback2: Second fallback (Ollama)
        """
        self.primary = primary
        self.fallback1 = fallback1
        self.fallback2 = fallback2

    async def send(
        self,
        messages: list[dict],
        context: Optional[dict] = None,
        timeout: int = 30,
    ) -> str:
        """
        Try providers in order until one succeeds.

        Returns:
            str: Response from first successful provider
        """
        providers = [self.primary, self.fallback1, self.fallback2]
        providers = [p for p in providers if p is not None]

        last_error = None
        for provider in providers:
            try:
                logger.info(
                    "trying_provider",
                    provider=provider.__class__.__name__,
                )
                response = await provider.send(messages, context, timeout)
                logger.info(
                    "provider_succeeded",
                    provider=provider.__class__.__name__,
                )
                return response

            except (TimeoutError, LLMError) as exc:
                last_error = exc
                logger.warning(
                    "provider_failed",
                    provider=provider.__class__.__name__,
                    error=str(exc),
                )
                continue

        # All providers failed
        raise LLMError(f"All LLM providers failed. Last error: {str(last_error)}")

    async def count_tokens(self, text: str) -> int:
        """Use primary provider for token counting."""
        if self.primary:
            return await self.primary.count_tokens(text)
        return len(text) // 4  # Fallback estimate


class LLMError(Exception):
    """Exception raised when LLM provider fails."""

    pass
