from dataclasses import dataclass


@dataclass
class Persona:
    id: str
    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_message: str = ""
    example_dialogue: str = ""
    custom_prompt: str = ""
    post_instructions: str = ""
    avatar_path: str = ""
    is_active: bool = False
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
