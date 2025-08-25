import asyncio
import json

import aiofiles


async def amain():
    data = {"test": "wow", "testing": "wowwww", "3": 4585}
    async with aiofiles.open("test.json", "w") as f:
        await f.write(json.dumps(data, indent=2, ensure_ascii=False))


asyncio.run(amain())
