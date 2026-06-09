"""Entry point: python -m gateway"""
import uvicorn

from .settings import GatewaySettings

if __name__ == "__main__":
    settings = GatewaySettings()
    uvicorn.run(
        "gateway.app:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
