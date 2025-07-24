"""
This is the main entry point for the actor, executed when you run `python3 -m src`.
It simply imports and runs the `main` function from the `main.py` file.
"""
import asyncio
from .main import main

# The Apify platform's event loop is already running, 
# so we need to schedule the main coroutine on it.
asyncio.run(main())
