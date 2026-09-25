"""
Fechas en UTC con zona explícita en todas las respuestas.

La base de datos guarda las fechas en UTC pero sin zona ("2026-09-20T05:57:23").
El navegador interpreta esas cadenas como hora LOCAL, así que en Perú (UTC-5)
todo se veía 5 horas adelantado. Aquí se añade "Z" a cualquier fecha-hora sin zona
antes de enviarla (respuestas HTTP y mensajes WebSocket).
"""
import re
from typing import Any

from fastapi.responses import JSONResponse

_NAIVE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?$")


def mark_utc(value: Any) -> Any:
    if isinstance(value, str):
        return value + "Z" if _NAIVE_ISO.match(value) else value
    if isinstance(value, dict):
        return {k: mark_utc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mark_utc(v) for v in value]
    return value


class UTCJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(mark_utc(content))
