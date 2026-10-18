"""LLM access. Returns None when no provider is configured: the agents then run
their deterministic heuristic fallback, so the pipeline never hard-depends on an API key."""

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings


def get_chat_model() -> BaseChatModel | None:
    s = get_settings()
    if s.llm_provider == "openai" and s.openai_api_key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=s.llm_model, api_key=s.openai_api_key, base_url=s.openai_base_url or None,
                          temperature=0, timeout=30, max_retries=1)
    if s.llm_provider == "anthropic" and s.anthropic_api_key:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=s.llm_model, api_key=s.anthropic_api_key, temperature=0, timeout=30, max_retries=1)
    return None


def structured(llm: BaseChatModel, schema):
    """Native JSON-schema output on OpenAI, tool calling everywhere else (Groq, Gemini, Anthropic...)."""
    s = get_settings()
    if s.llm_provider == "openai" and not s.openai_base_url:
        return llm.with_structured_output(schema)
    return llm.with_structured_output(schema, method="function_calling")
