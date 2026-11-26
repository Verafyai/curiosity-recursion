"""Start a run from the command line: python start_run.py examples/erastus.json"""
import asyncio, json, sys
from cr.client import start
from cr.models import ResearchRequest

async def main():
    req = ResearchRequest.model_validate(json.load(open(sys.argv[1])))
    print(await start(req))

asyncio.run(main())
