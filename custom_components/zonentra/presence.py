"""Pure presence and motion handling, modelled on Versatile Thermostat.

* Building presence (central configuration) applies to every zone. When the
  building is absent, zones use the *away* band.
* A zone may have a motion sensor. Motion counts after it lasted
  ``motion_delay_seconds`` and keeps counting for ``motion_off_delay_minutes``
  after it stopped. With motion: *comfort* band; without: *eco* band.
* Presence wins over motion. Unknown presence or a broken motion sensor never
  makes anyone cold: the zone stays on comfort.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .observations import SourceState

PRESENCE_DOMAINS = (
    "binary_sensor",
    "input_boolean",
    "alarm_control_panel",
    "person",
    "group",
    "zone",
)
BANDS = ("comfort", "eco", "away")


@dataclass(frozen=True)
class MotionMemory:
    confirmed: bool = False  # Motion lasted long enough during this period.


@dataclass(frozen=True)
class Occupancy:
    mode: str  # comfort / eco / away
    reason: str
    presence: str  # present / absent / unknown / not_configured
    motion: str  # active / inactive / unknown / not_configured


def read_presence(entity_id: str | None, source: SourceState | None) -> str:
    """present / absent / unknown / not_configured for one presence entity."""
    if not entity_id:
        return "not_configured"
    if source is None or source.state in (None, "unknown", "unavailable"):
        return "unknown"
    if not source.trustworthy:
        return "unknown"
    domain, state = entity_id.split(".", 1)[0], source.state
    if domain in ("binary_sensor", "input_boolean"):
        return {"on": "present", "off": "absent"}.get(state, "unknown")
    if domain == "group":
        return {"on": "present", "home": "present", "off": "absent"}.get(
            state, "absent" if state == "not_home" else "unknown"
        )
    if domain == "person":
        return "present" if state == "home" else "absent"
    if domain == "zone":  # State is the number of persons in the zone.
        try:
            return "present" if int(float(state)) > 0 else "absent"
        except ValueError:
            return "unknown"
    if domain == "alarm_control_panel":
        if state == "disarmed":
            return "present"
        return "absent" if state.startswith("armed_") else "unknown"
    return "unknown"


def motion_state(
    entity_id: str | None,
    source: SourceState | None,
    memory: MotionMemory,
    delay_seconds: float,
    off_delay_minutes: float,
    now: datetime,
) -> tuple[str, MotionMemory, datetime | None]:
    """(active / inactive / unknown / not_configured, memory, next check)."""
    if not entity_id:
        return "not_configured", MotionMemory(), None
    if (
        source is None
        or source.state not in ("on", "off")
        or not source.trustworthy
        or source.changed_at is None
    ):
        return "unknown", memory, None
    since = source.changed_at
    if source.state == "on":
        confirmed_at = since + timedelta(seconds=delay_seconds)
        if memory.confirmed or now >= confirmed_at:
            return "active", MotionMemory(True), None
        return "inactive", memory, confirmed_at
    until = since + timedelta(minutes=off_delay_minutes)
    if memory.confirmed and now < until:
        return "active", memory, until
    return "inactive", MotionMemory(False), None


def occupancy(presence: str, motion: str) -> Occupancy:
    if presence == "absent":
        return Occupancy("away", "building_absent", presence, motion)
    if motion == "inactive":
        return Occupancy("eco", "no_motion", presence, motion)
    reason = {
        "active": "motion",
        "unknown": "motion_sensor_unknown",
        "not_configured": "present" if presence == "present" else "default",
    }[motion]
    return Occupancy("comfort", reason, presence, motion)
