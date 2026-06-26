from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

AR_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

templates = Jinja2Templates(directory="app/templates")


def _localtime(value: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(AR_TZ).strftime(fmt)


templates.env.filters["localtime"] = _localtime
