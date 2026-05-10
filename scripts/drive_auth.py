"""One-time OAuth2 authorization flow. Generates token.json for Google Drive uploads.

Usage:
    uv run python -m scripts.drive_auth --client-secret /path/to/client_secret.json --token /path/to/token.json
"""

import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize Google Drive access and save token.json")
    parser.add_argument("--client-secret", required=True, help="Path to client_secret.json downloaded from Google Cloud Console")
    parser.add_argument("--token", required=True, help="Path to save the resulting token.json")
    args = parser.parse_args()

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, _SCOPES)
    creds = flow.run_local_server(port=0)

    with open(args.token, "w") as f:
        f.write(creds.to_json())

    print(f"Token saved to {args.token}")
    print(f"Add to .env:  GOOGLE_DRIVE_TOKEN_PATH={args.token}")


if __name__ == "__main__":
    main()
