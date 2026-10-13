"""Presets for cloud APIs that expose the OpenAI chat-completions protocol."""

CLOUD_PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
    },
    "gemini": {
        "label": "Google Gemini",
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
    },
    "openrouter": {
        "label": "OpenRouter",
        "api_key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openrouter/auto",
    },
    "groq": {
        "label": "Groq",
        "api_key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "deepseek": {
        "label": "DeepSeek",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "mistral": {
        "label": "Mistral",
        "api_key_env": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
    },
    "together": {
        "label": "Together AI",
        "api_key_env": "TOGETHER_API_KEY",
        "base_url": "https://api.together.xyz/v1",
        "model": "meta-llama/Meta-Llama-3.3-70B-Instruct-Turbo",
    },
    "xai": {
        "label": "xAI",
        "api_key_env": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-3-mini",
    },
    "ashna": {
        "label": "Ashna AI",
        "api_key_env": "ASHNA_API_KEY",
        "base_url": "https://api.ashna.ai/v1/api",
        "model": "gpt-6-astra",
    },
}

CUSTOM_PROVIDER = {
    "label": "OpenAI-compatible custom endpoint",
    "api_key_env": "CUSTOM_LLM_API_KEY",
}