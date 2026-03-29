"""Aion — subscription-native AI agent on claude-agent-sdk."""
__version__ = "0.2.0"

from .agent import AionAgent
from .config import AionConfig, load_config
from .schemas import SessionTitle, SessionSummary, SearchResult
from .llm import complete, complete_structured
