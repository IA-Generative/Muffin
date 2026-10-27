from pydantic_settings import BaseSettings, SettingsConfigDict


class EnergySettings(BaseSettings):
    """What turns the CPU time and memory a worker task used into an estimated energy (Wh): the workers
    run on shared hosts with no power meter, so this is a model, shown as an estimate - never a measure."""

    # Power one CPU core draws while it works (a server processor's TDP shared by its cores).
    ENERGY_WATTS_PER_CORE: float = 10.0
    # Power the memory a task holds draws, per GB, for as long as it runs (DRAM, ~0.3-0.4 W/GB).
    ENERGY_WATTS_PER_GB: float = 0.375
    # Power usage effectiveness of the data centre: what cooling and power distribution add on top.
    ENERGY_PUE: float = 1.2

    model_config = SettingsConfigDict(case_sensitive=True, env_file=(".env", ".env.local"), extra="ignore")
