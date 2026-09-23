"""FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from documind.core.container import Container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_current_user_id(container: ContainerDep) -> str:
    # Placeholder until Phase 4 (Cognito/JWT). Routes already depend on this, so adding real
    # auth changes this function only and every query stays scoped to the caller.
    return container.settings.dev_user_id


UserIdDep = Annotated[str, Depends(get_current_user_id)]
