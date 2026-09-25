"""Sign up / confirm / log in against a deployed environment's Cognito user pool (dev only).

Run these yourself; the password is read with a hidden prompt and never printed or saved.

    python backend/scripts/cognito_user.py signup  you@example.com
    python backend/scripts/cognito_user.py confirm you@example.com 123456   # code from email
    python backend/scripts/cognito_user.py login   you@example.com          # saves a token

The access token (valid 1 hour) is saved to ~/.documind/dev-token, where try_api.py picks it up
with --cognito. Pool and client ids are read from `terraform output` in infra/envs/<env>.
"""

import argparse
import getpass
import json
import subprocess
import sys
from pathlib import Path

import boto3

REPO = Path(__file__).resolve().parents[2]
TOKEN_DIR = Path.home() / ".documind"


def outputs(env: str) -> dict[str, str]:
    raw = subprocess.run(
        ["terraform", f"-chdir={REPO / 'infra' / 'envs' / env}", "output", "-json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {k: v["value"] for k, v in json.loads(raw).items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["signup", "confirm", "login"])
    parser.add_argument("email")
    parser.add_argument("code", nargs="?", help="verification code (confirm only)")
    parser.add_argument("--env", default="dev")
    args = parser.parse_args()

    out = outputs(args.env)
    client_id = out["cognito_app_client_id"]
    cognito = boto3.client("cognito-idp", region_name="us-east-1")

    if args.command == "signup":
        password = getpass.getpass("Choose a password (12+ chars, upper, lower, digit): ")
        cognito.sign_up(
            ClientId=client_id,
            Username=args.email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": args.email}],
        )
        print("Check your email for a 6-digit code, then run: confirm <email> <code>")
    elif args.command == "confirm":
        if not args.code:
            sys.exit("Usage: confirm <email> <code>")
        cognito.confirm_sign_up(ClientId=client_id, Username=args.email, ConfirmationCode=args.code)
        print("Confirmed. Now run: login <email>")
    else:
        password = getpass.getpass("Password: ")
        result = cognito.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": args.email, "PASSWORD": password},
        )["AuthenticationResult"]
        TOKEN_DIR.mkdir(exist_ok=True)
        path = TOKEN_DIR / f"{args.env}-token"
        path.write_text(result["AccessToken"], encoding="utf-8")
        path.chmod(0o600)
        print(f"Saved an access token (valid {result['ExpiresIn'] // 60} min) to {path}")
        print(f"API: {out['api_url']}")


if __name__ == "__main__":
    main()
