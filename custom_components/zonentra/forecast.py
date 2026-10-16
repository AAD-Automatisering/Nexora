"""Pure weather forecast logic (0.12): what the coming hours will bring.

Zonentra asks the weather entity for its hourly forecast (``weather.
get_forecasts``) and looks at the coming hours only. The expected maximum
makes the day warm, neutral or cold; that saves energy in two ways:

* screens: shade early on a warm day, let the sun in on a cold day;
* heating/cooling: on a warm day a room starts heating only further below its
  heating limit (the sun will warm it), on a cold day it starts cooling only
  further above its cooling limit (that heat is free). Fewer changeovers of the
  outdoor units, less gas and electricity.

Without a usable forecast everything works as before (day type unknown).
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from .temperature import convert_temperature

FORECAST_HOURS = 12  # Look this far ahead.
REFRESH_MINUTES = 30  # Ask the weather entity this often.
RETRY_SECONDS = 120  # Retry this soon while there is no forecast at all.
MAX_AGE_HOURS = 3  # Older forecasts are not used.


@dataclass(frozen=True)
class Forecast:
    maximum: float | None = None
    minimum: float | None = None
    hours: int = 0
    fetched_at: datetime | None = None


def _when(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return dt_util.parse_datetime(value)
    return None


def summarize_forecast(
    entries, now: datetime, hours: int = FORECAST_HOURS, *, temperature_unit="°C"
) -> Forecast:
    """Highest and lowest hourly temperatures in Celsius for the coming hours.

    The hour that is running now counts too (its entry starts before now).
    """
    start, end = now - timedelta(hours=1), now + timedelta(hours=hours)
    temperatures = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        when = _when(entry.get("datetime"))
        value = convert_temperature(entry.get("temperature"), temperature_unit)
        if when is None or value is None:
            continue
        if when.tzinfo is None:
            continue
        if start < when <= end:
            temperatures.append(float(value))
    if not temperatures:
        return Forecast(fetched_at=now)
    return Forecast(max(temperatures), min(temperatures), len(temperatures), now)


def forecast_usable(forecast: Forecast | None, now: datetime) -> bool:
    return (
        forecast is not None
        and forecast.maximum is not None
        and math.isfinite(forecast.maximum)
        and forecast.fetched_at is not None
        and now - forecast.fetched_at <= timedelta(hours=MAX_AGE_HOURS)
    )


def day_type(
    forecast: Forecast | None, now: datetime, warm_from: float, cold_to: float
) -> str:
    """warm (expected maximum >= warm_from), cold (<= cold_to) or neutral."""
    if not forecast_usable(forecast, now):
        return "unknown"
    if forecast.maximum >= warm_from:
        return "warm"
    if forecast.maximum <= cold_to:
        return "cold"
    return "neutral"


def demand_margins(kind: str, margin: float) -> tuple[float, float]:
    """(heating, cooling) start margin: wait for the free heat or cold."""
    if kind == "warm":
        return margin, 0.0
    if kind == "cold":
        return 0.0, margin
    return 0.0, 0.0
