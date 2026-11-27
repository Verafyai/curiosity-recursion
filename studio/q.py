import asyncio, sys
from studio.client import client
from studio.models import Progress
async def main():
    c = await client(); h = c.get_workflow_handle(sys.argv[1])
    p = await h.query("progress", result_type=Progress)
    print(p.status, p.stop_reason, len(p.questions))
    for l in p.log[-25:]: print(" ", l[:220])
    for q in p.questions: print(f"  {q.id:8} d{q.depth} {q.status:9} att{q.attempts} {q.text[:80]} | {q.answer[:90]}")
asyncio.run(main())
