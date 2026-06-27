import functools
import operator
import os
from pathlib import Path

import environ
from dotenv import load_dotenv

from disposition import Disposition

_original_environment = os.environ.copy()

load_dotenv(".env")

app_env = os.getenv("APP_ENV")
if app_env:
    load_dotenv(".env." + app_env, override=True)

load_dotenv(".env.local", override=True)
os.environ.update(_original_environment)

_str_to_disposition_map = {
    "1+kk": Disposition.FLAT_1KK,
    "1+1": Disposition.FLAT_1,
    "2+kk": Disposition.FLAT_2KK,
    "2+1": Disposition.FLAT_2,
    "3+kk": Disposition.FLAT_3KK,
    "3+1": Disposition.FLAT_3,
    "4+kk": Disposition.FLAT_4KK,
    "4+1": Disposition.FLAT_4,
    "5++": Disposition.FLAT_5_UP,
    "others": Disposition.FLAT_OTHERS
}

def dispositions_converter(raw_disps: str):
    return functools.reduce(operator.or_, map(lambda d: _str_to_disposition_map[d], raw_disps.split(",")), Disposition.NONE)


@environ.config(prefix="")
class Config:
    debug: bool = environ.bool_var()
    force_discord: bool = environ.bool_var(default=False)
    update_channel_topic: bool = environ.bool_var(default=False)
    found_offers_file: Path = environ.var(converter=Path)
    refresh_interval_daytime_minutes: int = environ.var(converter=int)
    refresh_interval_nighttime_minutes: int = environ.var(converter=int)
    dispositions: Disposition = environ.var(converter=dispositions_converter)
    embed_batch_size: int = environ.var(converter=int, default=10)

    @environ.config()
    class Discord:
        token = environ.var()
        offers_channel = environ.var(converter=int)
        dev_channel = environ.var(converter=int)

    discord: Discord = environ.group(Discord)

config: Config = Config.from_environ()
