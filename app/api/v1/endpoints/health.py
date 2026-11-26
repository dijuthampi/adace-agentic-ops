import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Response, status

from app.db.mysql import check_mysql_health
from app.db.postgres import check_pg_health
from app.schemas.health import HealthResponse, DatabaseStatus

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Dual-Database Connectivity Health Probe",
    description="Inspects real-time connection status and latency for both AdAce MySQL and Agent State PostgreSQL.",
)
async def get_health(response: Response) -> HealthResponse:
    # Run health probes concurrently
    mysql_result, pg_result = await asyncio.gather(
        check_mysql_health(),
        check_pg_health(),
    )

    mysql_status = DatabaseStatus(
        connected=mysql_result["connected"],
        message=mysql_result["message"],
        latency_ms=mysql_result.get("latency_ms"),
    )
    pg_status = DatabaseStatus(
        connected=pg_result["connected"],
        message=pg_result["message"],
        latency_ms=pg_result.get("latency_ms"),
    )

    if mysql_status.connected and pg_status.connected:
        overall_status = "healthy"
    elif mysql_status.connected or pg_status.connected:
        overall_status = "degraded"
        response.status_code = status.HTTP_200_OK
    else:
        overall_status = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall_status,
        mysql=mysql_status,
        postgres=pg_status,
        timestamp=datetime.now(timezone.utc),
    )
