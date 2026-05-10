from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Mega AI"
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/mega_ai"
    
    # LLM Settings (Defaulting to local-first)
    LLM_MODEL: str = "llama3" 
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    
    # Context Budgets
    MAX_CONTEXT_TOKENS: int = 4096

    class Config:
        env_file = ".env"

settings = Settings()