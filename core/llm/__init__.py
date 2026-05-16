from dataclasses import dataclass


@dataclass
class ProviderConfig:
    id: str
    name: str
    provider_type: str = "openai_compatible"
    category: str = "chat"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.8
    max_tokens: int = 512
    is_default: bool = False
