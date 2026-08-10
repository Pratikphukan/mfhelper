import asyncio
import os
import sys
from pathlib import Path

# Add current folder to path
agent_dir = Path(__file__).resolve().parent
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

from dotenv import load_dotenv
load_dotenv(agent_dir / ".env")

from contextlib import AsyncExitStack
from mcp_client import MCPClient
from core.claude import Claude
from core.cli_chat import CliChat

async def main():
    claude_model = os.getenv("CLAUDE_MODEL", "")
    claude_service = Claude(model=claude_model)
    
    async with AsyncExitStack() as stack:
        server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
        doc_client = await stack.enter_async_context(
            MCPClient(command=sys.executable, args=[server_path])
        )
        chat = CliChat(
            doc_client=doc_client,
            clients={"doc_client": doc_client},
            claude_service=claude_service,
        )
        
        print("--- RUNNING QUERY 1 ---")
        response1 = await chat.run("What is the content of @report.pdf?")
        print("RESPONSE 1:", response1)
        
        print("\n--- RUNNING QUERY 2 ---")
        response2 = await chat.run("Show me all worksheet tabs inside my Google Sheet")
        print("RESPONSE 2:", response2)

if __name__ == "__main__":
    asyncio.run(main())
