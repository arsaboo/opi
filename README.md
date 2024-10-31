# OPI - Option passive income bot

The DIY alternative to rolling calls in your portfolio.

This bot is meant for my own personal use, the strategy behind it is subject to change.

That said, you are free to use this bot in any way you see fit, as long as you understand what's written here and what the code of this bot does.

If you don't understand everything 100%, then don't use it!

### Requirements

- A Schwab account with options privileges
- All python packages from requirements.txt installed
- General understanding of the stock market and options

### Setup instructions

1. Register and create an app on [developer.schwab.com](https://developer.schwab.com/) to get an API key
2. Copy configuration.example.py to configuration.py and adjust it to your needs
3. Run main.py

### Debug Mode and Market Status

The bot operates based on both market status and debug mode settings:

- When market is open: The bot will run normally with the message "Market is open, running the program now..."
- When market is closed:
  - If debug mode is enabled (`debugMarketOpen = True` in configuration.py): The bot will run with the message "Market is closed but the program will work in debug mode."
  - If debug mode is disabled (`debugMarketOpen = False`): The bot will wait for market open with the message "Market is closed."

Debug mode is useful for testing and development purposes when the market is closed.

## Factsheet

This bot seeks to generate passive income from option premiums through rolling covered calls on stocks and ETF's.

The bot is designed to manage calls that you have created on the assets of your choice.

The bot does not create new covered calls. Instead, it focuses on rolling existing covered calls each month.

You can configure the roll-up or roll-out settings in the configuration file.

---

Please note: The creation of new covered calls is a manual process and must be done by the user.
---
### Rollups: Further explanation

A 'rollup' is the process of rolling to a higher strike price than the current one.

You can use `minRollupGap` to configure the roll, you should have some spare cash in the account to pay for rollup costs, because the new contract can have less premium than the current one,
if the asset price went up.

### Risks

**Volatility risk** - Less volatility, more spread, less option premium

Do not use this bot with assets that have low volatility or too few options

**Options** - Covered calls are the least risky options, nonetheless, if you don't know what you're doing or fuck up the configuration above, you can lose a lot or even all of your
money

**Early assignment** - If your cc's end up being significantly ITM before expiration, there is a low chance that you get assigned and your brokerage automatically closes the cc's
and sells the according amount of shares.

If this happens, the bot will fail and notify you, but you will need to manually buy everything back, before restarting the bot.
