"""JWT verification for local (HS256) and Cognito (RS256) tokens, including attack cases."""

import time
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from documind.core.auth import (
    LOCAL_AUDIENCE,
    LOCAL_ISSUER,
    CognitoAuthenticator,
    LocalAuthenticator,
    build_authenticator,
)
from documind.core.config import AuthMode, Settings
from documind.core.errors import UnauthorizedError

SECRET = "x" * 40


class TestLocalAuthenticator:
    def test_round_trip(self) -> None:
        auth = LocalAuthenticator(SECRET)
        assert auth.authenticate(auth.issue("alice")).user_id == "alice"

    def test_rejects_expired_token(self) -> None:
        auth = LocalAuthenticator(SECRET)
        with pytest.raises(UnauthorizedError):
            auth.authenticate(auth.issue("alice", ttl_seconds=-120))

    def test_rejects_token_signed_with_another_secret(self) -> None:
        forged = LocalAuthenticator("y" * 40).issue("alice")
        with pytest.raises(UnauthorizedError):
            LocalAuthenticator(SECRET).authenticate(forged)

    def test_rejects_unsigned_alg_none_token(self) -> None:
        # Classic JWT attack: strip the signature and claim "alg": "none".
        claims = {
            "sub": "admin",
            "iss": LOCAL_ISSUER,
            "aud": LOCAL_AUDIENCE,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        }
        unsigned = jwt.encode(claims, key="", algorithm="none")
        with pytest.raises(UnauthorizedError):
            LocalAuthenticator(SECRET).authenticate(unsigned)

    @pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c"])
    def test_rejects_garbage(self, token: str) -> None:
        with pytest.raises(UnauthorizedError):
            LocalAuthenticator(SECRET).authenticate(token)


REGION, POOL, CLIENT = "us-east-1", "us-east-1_TEST", "client123"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def cognito(rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch) -> CognitoAuthenticator:
    auth = CognitoAuthenticator(REGION, POOL, CLIENT)
    # Serve our test public key instead of fetching the pool's JWKS over the network.
    monkeypatch.setattr(
        auth._jwks,
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=rsa_key.public_key()),
    )
    return auth


def cognito_token(key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "sub": "user-42",
        "iss": ISSUER,
        "token_use": "access",
        "client_id": CLIENT,
        "iat": now,
        "exp": now + 3600,
    } | overrides
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


class TestCognitoAuthenticator:
    def test_accepts_valid_access_token(
        self, cognito: CognitoAuthenticator, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        assert cognito.authenticate(cognito_token(rsa_key)).user_id == "user-42"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"token_use": "id"},  # ID tokens are for the client, not for calling APIs
            {"client_id": "someone-elses-app"},
            {"iss": "https://cognito-idp.us-east-1.amazonaws.com/other_pool"},
            {"exp": int(time.time()) - 600},
        ],
    )
    def test_rejects_tokens_not_meant_for_this_api(
        self, cognito: CognitoAuthenticator, rsa_key: rsa.RSAPrivateKey, overrides: dict[str, Any]
    ) -> None:
        with pytest.raises(UnauthorizedError):
            cognito.authenticate(cognito_token(rsa_key, **overrides))

    def test_rejects_token_signed_by_another_key(self, cognito: CognitoAuthenticator) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(UnauthorizedError):
            cognito.authenticate(cognito_token(other))


def test_build_authenticator_requires_a_secret_in_local_mode() -> None:
    with pytest.raises(RuntimeError, match="DOCUMIND_JWT_SECRET"):
        build_authenticator(Settings(_env_file=None, auth_mode=AuthMode.LOCAL, jwt_secret=None))
    with pytest.raises(ValueError, match="at least 32"):
        Settings(_env_file=None, jwt_secret="short")
