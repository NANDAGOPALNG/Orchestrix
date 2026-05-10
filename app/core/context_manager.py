import tiktoken
from app.schemas.shared_context import SharedContext

class ContextManager:
    def __init__(self, model: str = "gpt-3.5-turbo"): # tiktoken uses this for encoding
        self.encoder = tiktoken.encoding_for_model(model)

    def count_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    def check_budget(self, context: SharedContext, new_text: str):
        new_tokens = self.count_tokens(new_text)
        if (context.total_tokens + new_tokens) > context.max_budget:
            # This is where you'd trigger the Compression Agent (Requirement 3)
            return False, new_tokens
        return True, new_tokens