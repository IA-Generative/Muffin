from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    """The MCP search tools (#467): what a call uses when it does not say, and the most it may ask for."""

    # The chat model that splits a question into sub-questions. Empty: the hub's first chat model, like a pipeline
    # step with no model configured.
    MCP_SEARCH_MODEL: str = ""
    # Defaults of `search`...
    MCP_SEARCH_MAX_SUB_QUERIES: int = 4
    MCP_SEARCH_MAX_COLLECTIONS: int = 3
    MCP_SEARCH_LIMIT: int = 5
    # ...and the ceilings no call goes over, whatever it asks.
    MCP_SEARCH_MAX_SUB_QUERIES_CEILING: int = 8
    MCP_SEARCH_MAX_COLLECTIONS_CEILING: int = 10
    MCP_SEARCH_LIMIT_CEILING: int = 20
    # `suggest_collections`.
    MCP_SUGGEST_LIMIT: int = 5
    MCP_SUGGEST_LIMIT_CEILING: int = 20

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
