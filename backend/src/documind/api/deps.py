"""FastAPI dependencies."""

import asyncio
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from documind.core.auth import Authenticator
from documind.core.container import Container
from documind.core.errors import UnauthorizedError

# auto_error=False: we raise our own 401 so errors keep the standard {"error": {...}} shape.
_bearer = HTTPBearer(auto_error=False, description="JWT access token (Cognito, or a dev token)")


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_current_user_id(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """The authenticated caller's id (the token's ``sub``). Every route that touches user data
    depends on this, and every repository call is scoped by the value it returns."""
    if credentials is None:
        raise UnauthorizedError("Missing bearer token.")
    authenticator: Authenticator = request.app.state.authenticator
    # Cognito verification may fetch signing keys over HTTP on first use; keep the loop free.
    principal = await asyncio.to_thread(authenticator.authenticate, credentials.credentials)
    return principal.user_id


UserIdDep = Annotated[str, Depends(get_current_user_id)]
