# Options Trading UI

This directory contains the modern terminal user interface for the Options Trading application, built with [Textual](https://textual.textualize.io/).

## Features

- **Instant screen switching** - Tables appear immediately when switching screens (no loading delays)
- **Progressive data loading** - Data populates in real-time as it becomes available
- **Seamless transitions** - Switch between screens instantly with proper table structure
- Modern, interactive terminal interface
- Real-time market status display
- Keyboard shortcuts for quick navigation
- Dedicated screens for different operations
- Async operations for smooth user experience

## Installation

All dependencies are included in the main requirements.txt file:

```bash
pip install -r requirements.txt
```

## Usage

The UI automatically starts when you run the main application:

```bash
python main.py
```

## Keyboard Shortcuts

- `q` - Quit the application
- `1` - Roll Short Options
- `2` - Check Box Spreads
- `3` - Check Vertical Spreads
- `4` - Check Synthetic Covered Calls
- `5` - View Margin Requirements
- `6` - View/Cancel Orders
- `Escape` - Go back (in sub-screens)
- `Enter` - Select item (in tables)

## Performance Features

The UI is optimized for maximum responsiveness:
- **Instant screen switches** - Empty tables with proper columns appear immediately
- **No loading screens** - Clean, immediate transitions between all screens
- **Progressive data population** - Data fills in as it becomes available
- **Real-time updates** - All screens show live progress as data loads
- **Smooth navigation** - Zero delay when switching between different option screens

## File Structure

- `ui_main.py` - Main entry point for the UI
- `screen_main.py` - Main menu screen with instant table switching
- `styles.css` - Textual CSS styling
- `ui_utils.py` - Data processing utilities

## Development

The UI is designed to be modular and extensible. Each screen is a separate component that can be modified independently.

To add new screens:
1. Create a new file `screen_*.py`
2. Inherit from `Screen` class
3. Implement the `compose()` method for layout
4. Add navigation logic in the main screen