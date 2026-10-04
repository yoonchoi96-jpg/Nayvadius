from dataclasses import dataclass
import os

@dataclass
class Settings:
    state_path: str = os.getenv("NAYVADIUS_STATE_PATH", "data/nayvadius.db")
    output_path: str = os.getenv("NAYVADIUS_OUTPUT_PATH", "output")

settings = Settings()
