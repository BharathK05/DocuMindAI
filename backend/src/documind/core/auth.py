"""Bearer-token authentication.

Every request carries ``Authorization: Bearer <JWT>``. The token's ``sub`` claim becomes the
user id, and every repository call is scoped by it, which is what keeps tenants apart.

* ``CognitoAuthenticator`` (AWS): RS256 access tokens issued by an Amazon Cognito user pool,
  verified against the pool's published public keys (JWKS). We never see passwords.
* ``LocalAuthenticator`` (development): HS256 tokens signed with a shared secret, so local
  development needs no AWS account. ``issue`` exists only here.
"""

import time
from dataclasses import dataclass
from typing import Any, Protocol

import jwt

from documind.core.config import AuthMode, Settings
from documind.core.errors import UnauthorizedError

LOCAL_ISSUER = "documind-local"
LOCAL_AUDIENCE = "documind"
_LEEWAY_SECONDS = 30  # tolerate small clock skew between issuer and verifier


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str


class Authenticator(Protocol):
    def authenticate(self, token: str) -> Principal: ...


def _principal(claims: dict[str, Any]) -> Principal:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise UnauthorizedError("Token has no subject.")
    return Principal(subject)


class LocalAuthenticator:
    def __init__(self, secret: str) -> None:
        self._secret = secret

    def issue(self, user_id: str, ttl_seconds: int = 12 * 3600) -> str:
        now = int(time.time())
        claims = {
            "sub": user_id,
            "iss": LOCAL_ISSUER,
            "aud": LOCAL_AUDIENCE,
            "iat": now,
            "exp": now + ttl_seconds,
        }
        return jwt.encode(claims, self._secret, algorithm="HS256")

    def authenticate(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],  # pinned: never let the token choose (e.g. "none")
                audience=LOCAL_AUDIENCE,
                issuer=LOCAL_ISSUER,
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Invalid or expired token.") from exc
        return _principal(claims)


class CognitoAuthenticator:
    def __init__(self, region: str, user_pool_id: str, app_client_id: str) -> None:
        self._issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._client_id = app_client_id
        # Keys are fetched once and cached; Cognito rotates them rarely.
        self._jwks = jwt.PyJWKClient(f"{self._issuer}/.well-known/jwks.json", lifespan=3600)

    def authenticate(self, token: str) -> Principal:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                leeway=_LEEWAY_SECONDS,
                # Cognito access tokens carry client_id instead of aud; checked below.
                options={"require": ["exp", "iat", "sub", "token_use"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("Invalid or expired token.") from exc
        if claims.get("token_use") != "access" or claims.get("client_id") != self._client_id:
            raise UnauthorizedError("Token was not issued for this application.")
        return _principal(claims)


def build_authenticator(settings: Settings) -> Authenticator:
    if settings.auth_mode is AuthMode.COGNITO:
        assert settings.cognito_user_pool_id and settings.cognito_app_client_id  # validated
        return CognitoAuthenticator(
            settings.aws_region, settings.cognito_user_pool_id, settings.cognito_app_client_id
        )
    if settings.jwt_secret is None:
        raise RuntimeError(
            "DOCUMIND_JWT_SECRET is not set. Add a random 32+ character value to backend/.env "
            "(see .env.example)."
        )
    return LocalAuthenticator(settings.jwt_secret.get_secret_value())
