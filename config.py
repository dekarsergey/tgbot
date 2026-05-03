import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    BOT_TOKEN: str = ""
    ADMIN_IDS: list = None               # Список Telegram ID админов
    CHANNEL_ID: str = ""                 # @username или -100xxxxxxxxxx
    DB_PATH: str = "bot_data.db"

    def __post_init__(self):
        self.BOT_TOKEN = self._require("BOT_TOKEN")
        self.CHANNEL_ID = self._require("CHANNEL_ID")
        self.DB_PATH = os.getenv("DB_PATH", "bot_data.db")

        raw_admins = self._require("ADMIN_IDS")
        try:
            self.ADMIN_IDS = [int(x.strip()) for x in raw_admins.split(",")]
        except ValueError:
            raise ValueError("ADMIN_IDS must be comma-separated integers, e.g. 123456789,987654321")

    @staticmethod
    def _require(key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise EnvironmentError(
                f"Required environment variable '{key}' is missing. "
                f"Check your .env file."
            )
        return value
