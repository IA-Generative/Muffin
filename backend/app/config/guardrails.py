from pydantic_settings import BaseSettings, SettingsConfigDict


class GuardrailSettings(BaseSettings):
    """The guardrails on what a person writes (#516). What an administrator defines - which guardrails, their mode,
    their stage, the policy of the whole - is stored in the application; these are the limits no setting may lift."""

    # What a guardrail is shown at most: the rest of a very long message is not looked at by a model nor sent to a
    # service, and a rule that wants the length has the whole text.
    GUARDRAILS_TEXT_MAX_CHARS: int = 20000
    # The longest a pattern of a `rules` guardrail may be, and how many patterns and terms one may hold: a pattern is
    # run on every message of everyone.
    GUARDRAILS_PATTERN_MAX_CHARS: int = 500
    GUARDRAILS_PATTERNS_MAX: int = 50
    GUARDRAILS_TERMS_MAX: int = 2000
    # The most guardrails there can be, and the longest wait an administrator may give one or the whole (milliseconds).
    GUARDRAILS_MAX: int = 50
    GUARDRAILS_TIMEOUT_LIMIT_MS: int = 30000
    # Hosts (comma-separated) a guardrail of type `http` may call although they are on a private network: an internal
    # moderation service. Nothing else that is not public is ever reached.
    GUARDRAILS_ALLOWED_PRIVATE_HOSTS: str = ""
    # How long the results are kept (days): verdicts and counts, never the text.
    GUARDRAILS_RESULTS_RETENTION_DAYS: int = 180

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")

    @property
    def allowed_private_hosts(self) -> set[str]:
        return {host.strip().lower() for host in self.GUARDRAILS_ALLOWED_PRIVATE_HOSTS.split(",") if host.strip()}
