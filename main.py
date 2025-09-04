"""
Options Trading Bot - Main Entry Point

This is the main entry point for the Options Trading Bot application.
It launches the Textual UI which provides a terminal-based graphical interface
for all the bot's functionality.
"""

import sys
import argparse
import os
import atexit
import asyncio
import alert
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from api import Api
from ui.main import OpiApp
from api.streaming.provider import get_provider
from state_manager import save_symbols

# Get API credentials from environment variables
apiKey = os.getenv("SCHWAB_API_KEY")
apiRedirectUri = os.getenv("SCHWAB_REDIRECT_URI")
appSecret = os.getenv("SCHWAB_APP_SECRET")
SchwabAccountID = os.getenv("SCHWAB_ACCOUNT_ID")

# Validate that all required environment variables are present
if not all([apiKey, apiRedirectUri, appSecret, SchwabAccountID]):
    print("ERROR: Missing required environment variables. Please check your .env file.")
    print("Required variables: SCHWAB_API_KEY, SCHWAB_REDIRECT_URI, SCHWAB_APP_SECRET, SCHWAB_ACCOUNT_ID")
    sys.exit(1)


def setup_api_with_retry(api, max_attempts=3):
    """Set up the API with retry logic specifically for authentication errors"""
    for attempt in range(1, max_attempts + 1):
        try:
            api.setup()
            return True  # If setup is successful, return True
        except Exception as e:
            error_str = str(e)
            print(f"Error while setting up the api: {error_str}")

            # Check if this is the last attempt
            is_last_attempt = attempt >= max_attempts

            # Handle token authentication error
            if "refresh_token_authentication_error" in error_str and not is_last_attempt:
                print("Token authentication failed. Deleting existing token and retrying...")
                api.delete_token()

            # Exit if max attempts reached
            if is_last_attempt:
                print(f"Failed to initialize API after {max_attempts} attempts")
                return False

            # Retry with delay
            print(f"Retrying setup (attempt {attempt}/{max_attempts})...")
            import time
            time.sleep(2) # Brief pause before retry

    return False # Should not reach here, but added as a fallback


def main():
    """Main entry point for the Options Trading Bot with Textual UI."""
    # Create argument parser
    parser = argparse.ArgumentParser(
        description="Options Trading Bot with Textual UI",
        epilog="Launch the application to access all trading features through the terminal interface."
    )

    # Add any custom arguments here if needed in the future
    # For now, we're just using the default --help that argparse provides

    # Parse arguments (this will automatically handle --help)
    try:
        args = parser.parse_args()
    except SystemExit:
        # argparse calls sys.exit() when --help is used, which is what we want
        return

    # Initialize and setup API
    print("Initializing API and validating token...")
    api = Api(apiKey, apiRedirectUri, appSecret)

    if not setup_api_with_retry(api):
        print("Failed to initialize API. Exiting...")
        try:
            alert.botFailed(None, "Failed to initialize API after retries.")
        except Exception:
            pass
        sys.exit(1)

    print("API initialized successfully. Launching Textual UI...")

    # Launch the Textual UI
    try:
        # Best-effort save on interpreter exit as a safety net
        def _save_state_on_exit():
            try:
                prov = get_provider(api.connectClient)
                syms = list(prov.get_all_subscribed()) if prov else []
                save_symbols(SchwabAccountID, syms)
            except Exception:
                pass
        atexit.register(_save_state_on_exit)
        app = OpiApp(api)
        app.run()
    except KeyboardInterrupt:
        print("\nExiting...")
        # Try to stop provider cleanly; don't let it hang exit
        try:
            prov = get_provider(api.connectClient)
            if prov:
                asyncio.run(prov.stop())
        except Exception:
            pass
        # Force terminate to avoid occasional hang
        os._exit(0)
    except Exception as e:
        print(f"Error running the application: {e}")
        try:
            prov = get_provider(api.connectClient)
            if prov:
                asyncio.run(prov.stop())
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()

