import sys
import os
import traceback
from logger import get_logger

# Add the current directory to path for local imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Add the parent directory to the path so we can import from main
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Ensure we're only importing from screen_main, not screen_main_new
import screen_main

logger = get_logger()


def run_textual_app(api):
    """Run the Textual-based UI application"""
    try:
        app = screen_main.OptionsTradingApp(api)
        app.run()
    except Exception as e:
        print("\n[Textual UI Exception Traceback]")
        traceback.print_exc()
        if "I/O operation on closed file" in str(e):
            raise RuntimeError("UI failed to start due to I/O access issues. This may be due to stdin/stdout not being available in your terminal environment.")
        else:
            raise RuntimeError(f"UI failed to start: {str(e)}")


# Ensure roll short options functionality is properly implemented
def setup_roll_short_options(self):
    """Setup roll short options functionality."""
    try:
        # Import roll functions from cc.py
        from cc import RollCalls, RollSPX

        def handle_roll_short_options():
            try:
                # Get short positions from API
                short_positions = self.api.getShortOptions()

                if not short_positions:
                    print("No short options positions found")
                    return

                # Process each short position
                for position in short_positions:
                    try:
                        symbol = position.get("stockSymbol", "")
                        print(f"Processing roll for {symbol}")

                        if symbol == "$SPX":
                            RollSPX(self.api, position)
                        else:
                            RollCalls(self.api, position)
                    except Exception as roll_error:
                        print(f"Error rolling {symbol}: {str(roll_error)}")
                        logger.error(f"Error rolling {symbol}: {roll_error}")

            except Exception as e:
                print(f"Error loading short options: {str(e)}")
                logger.error(f"Error in roll short options: {e}")

        return handle_roll_short_options

    except ImportError as e:
        logger.error(f"Failed to import roll functions: {e}")
        return None


def main():
    # Use screen_main.MainMenuScreen and screen_main.OptionsTradingApp
    # Remove any references to screen_main_new
    pass


if __name__ == "__main__":
    # For testing purposes - in real usage this will be called from main.py
    print("UI module - should be imported from main.py")
