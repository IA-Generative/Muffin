"""The guardrails on what a person writes (#516): checks that run before anything of the request goes to a model.

A guardrail is of one of three types - `rules` (code), `llm` (a model of the hub classifies the request), `http`
(a service outside, with a contract that is fixed) - and says what to do when it flags: block, warn, redact or only
monitor.
`runner.evaluate` runs them by stages, the guardrails of a stage together, and decides with the policy of the whole."""
