"""Entry point for running the MCP server: python -m src"""

from src.server import main
import asyncio

asyncio.run(main())
