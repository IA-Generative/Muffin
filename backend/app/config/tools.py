from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolSettings(BaseSettings):
    """The tools the chat may call (#343): Muffin's own and those of MCP servers the users add."""

    # Only these domains (and their subdomains) may be the address of a tool server, comma separated. Empty: any
    # public address - never a private one, see TOOLS_ALLOW_PRIVATE_ADDRESSES.
    TOOLS_ALLOWED_DOMAINS: str = ""
    # For a developer's machine only: lets a server be on a private or local address. Never in production - a tool
    # server on the internal network is the way into it (SSRF).
    TOOLS_ALLOW_PRIVATE_ADDRESSES: bool = False
    # What one call may take, and how much of its answer is kept (characters): what a server sends back is not trusted
    # to be short.
    TOOLS_CALL_TIMEOUT_SECONDS: float = 20.0
    TOOLS_OUTPUT_MAX_CHARS: int = 6000
    # How many calls one run may make and one person per minute; past that a call answers `quota_depasse`, and nothing
    # fails.
    TOOLS_CALLS_PER_RUN: int = 5
    TOOLS_CALLS_PER_USER_PER_MINUTE: int = 30
    # A request to run a tool that changes data waits this long for the person's answer (hours), and a person may
    # have at most this many waiting: past either, it is dropped / refused rather than piling up.
    TOOLS_PENDING_HOURS: int = 24
    TOOLS_PENDING_PER_USER: int = 20
    # How many tool servers a person may add, and how many tools are described to the model at once.
    TOOL_SERVERS_PER_USER: int = 10
    TOOLS_OFFERED_MAX: int = 12
    # The tools of a server are imported again when it is synchronised: how many it may bring at most.
    TOOLS_PER_SERVER_MAX: int = 100

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")

    @property
    def allowed_domains(self) -> list[str]:
        return [item.strip().lower().lstrip(".") for item in self.TOOLS_ALLOWED_DOMAINS.split(",") if item.strip()]
