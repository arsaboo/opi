"""
UI Package for Options Trading Application

This package contains the Textual-based terminal user interface components.
It provides a modern, interactive terminal interface for options trading operations.

Components:
- ui_main: Main entry point for the UI application
- screen_main: Main menu screen with options and navigation
- screen_spreads_table: Dedicated screen for displaying spreads data
- styles.css: Styling for the Textual application
"""

__version__ = "1.0.0"
__author__ = "Options Trading System"

# UI package - consolidated to use only screen_main.py
from .screen_main import MainMenuScreen, OptionsTradingApp

__all__ = [
    'OptionsTradingApp',
    'MainMenuScreen'
]
