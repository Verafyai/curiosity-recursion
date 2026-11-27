"""Browser test of Explore mode, items 1 to 3 of the spec, against a throwaway Temporal dev server.

1. the person node shows its brainstormed questions within seconds, with a spinner and streamed activity
2. click to explore with permission (confirm, and a second confirm over the threshold), three levels deep
3. Dig deeper and Add question on a leaf

The worker uses the fixture activities (studio.fakes, records titled [TEST FIXTURE]) so nothing touches the network.
Needs the temporal CLI and Playwright's chromium (../.venv/bin/python -m playwright install chromium).
Set STUDIO_SHOTS=dir to save screenshots.

    cd studio && ../.venv/bin/python -m pytest -q tests/test_ui_playwright.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pw = pytest.importorskip("playwright.sync_api")
TEMPORAL = shutil.which("temporal")
pytestmark = pytest.mark.skipif(TEMPORAL is None, reason="needs the temporal CLI")
SHOTS = os.environ.get("STUDIO_SHOTS")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Stack:
    """Temporal dev server + Studio worker + web app, all in one background event loop."""

    def __init__(self):
        self.port = _free_port()
        self.ready = threading.Event()
        self.stop = None
        self.err = None

    async def main(self):
        from temporalio.contrib.pydantic import pydantic_data_converter
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker
        import uvicorn
        try:
            env = await WorkflowEnvironment.start_local(data_converter=pydantic_data_converter, dev_server_existing_path=TEMPORAL,
                                                        dev_server_extra_args=["--log-level", "error"])
            os.environ["TEMPORAL_ADDRESS"] = env.client.service_client.config.target_host
            os.environ["STUDIO_FAKE_DELAY"] = "1.2"
            os.environ["STUDIO_CONFIRM_OVER_CALLS"] = "1"  # so a 2-call pass needs the second confirm
            tq = f"ui-{uuid.uuid4().hex[:6]}"
            os.environ["STUDIO_TASK_QUEUE"] = tq
            import importlib
            import studio.client as sc
            import studio.fakes as fk
            importlib.reload(sc)
            importlib.reload(fk)
            from studio import activities as a
            from studio.explore_activities import seed_questions
            from studio.explore_workflows import ExploreRunWorkflow, ResearchPassWorkflow
            import web.app as webapp
            importlib.reload(webapp)
            worker = Worker(env.client, task_queue=tq, workflows=[ExploreRunWorkflow, ResearchPassWorkflow],
                            activities=[seed_questions, fk.fake_investigate, fk.fake_step, a.compose_report, a.export_outreach])
            server = uvicorn.Server(uvicorn.Config(webapp.app, host="127.0.0.1", port=self.port, log_level="warning"))
            self.stop = asyncio.Event()
            async with env, worker:
                task = asyncio.create_task(server.serve())
                while not server.started:
                    await asyncio.sleep(0.05)
                self.ready.set()
                await self.stop.wait()
                server.should_exit = True
                await task
        except Exception as e:  # surface setup errors to the test thread
            self.err = e
            self.ready.set()

    def __enter__(self):
        self.loop = asyncio.new_event_loop()
        self.t = threading.Thread(target=self.loop.run_until_complete, args=(self.main(),), daemon=True)
        self.t.start()
        self.ready.wait(60)
        if self.err:
            raise self.err
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *a):
        self.loop.call_soon_threadsafe(self.stop.set)
        self.t.join(30)


def shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"{name}.png"), full_page=False)


def test_explore_ui_three_levels_dig_and_add():
    with Stack() as base, pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1680, "height": 1050})
        page.goto(base + "/?ex=erastus")
        page.wait_for_selector("#circuit_id option", state="attached")
        page.fill("#full_name", "Erastus W. Burnham")
        t0 = time.time()
        page.click("button[type=submit]")
        # 1. questions on the person node within a few seconds; activity is streamed
        page.wait_for_selector(".xq[data-qid^='person-q']", timeout=8000)
        assert time.time() - t0 < 8
        assert page.locator(".xq[data-qid^='person-q']").count() >= 5
        assert page.locator(".xq .gen", has_text="circuit checklist").count() >= 1
        page.wait_for_function("document.getElementById('stream').textContent.includes('questions brainstormed')", timeout=5000)
        shot(page, "1-person-questions")
        # 2. three levels: confirm, watch the spinner, land on the new child node
        saw_second_confirm = False
        for level in (1, 2, 3):
            row = page.locator("#panel .xq").filter(has=page.locator("button", has_text="Research this")).first
            qid = row.get_attribute("data-qid")
            over = "about 1 call)" not in row.inner_text()
            row.locator("button", has_text="Research this").click()
            page.locator(f"#q-{qid} .confirm").wait_for()
            page.locator(f"#q-{qid} button", has_text="Yes, research it").click()
            if over:  # over the 1-call threshold set above: a second confirm before anything runs
                page.locator(f"#q-{qid} .confirm.over").wait_for()
                shot(page, "4-second-confirm")
                saw_second_confirm = True
                page.locator(f"#q-{qid} button", has_text="Run it anyway").click()
            page.wait_for_selector(f"#q-{qid} .spinner", timeout=3000)
            if level == 1:
                shot(page, "2-running")
            page.wait_for_selector(f"#q-{qid} .ans a", timeout=15000)  # the answer links the child nodes it produced
            child = page.locator(f"#q-{qid} .ans a").first.inner_text()
            page.locator(f"#q-{qid} .ans a").first.click()
            page.wait_for_function(f"document.querySelector('#panel .eyebrow').textContent.includes('level {level}')", timeout=5000)
            assert page.locator("#panel .tier.possible").count() >= 1
        shot(page, "3-three-levels")
        assert page.locator("#cy").count() == 1 and page.evaluate("cy.nodes().length") >= 7
        if not saw_second_confirm:  # make sure the second confirm is exercised at least once
            q = page.locator("#panel .xq").filter(has=page.locator("button", has_text="Research this")).filter(has_text="about 2 calls")
            if q.count():
                qid = q.first.get_attribute("data-qid")
                q.first.locator("button", has_text="Research this").click()
                page.locator(f"#q-{qid} button", has_text="Yes, research it").click()
                page.locator(f"#q-{qid} .confirm.over").wait_for()
                page.locator(f"#q-{qid} button", has_text="Cancel").click()
        # 3. the leaf offers Dig deeper and Add question, prominently
        assert page.locator("#panel .leafbox").count() == 1
        before = page.locator("#panel .xq").count()
        page.click("#dig")
        page.wait_for_function(f"document.querySelectorAll('#panel .xq').length > {before}", timeout=8000)
        assert page.locator("#panel .xq .gen", has_text="dig deeper").count() >= 1
        page.fill("#addq", "Was he at Port Hudson in 1863?")
        page.click("#panel form button[type=submit]")
        page.locator("#panel .xq", has_text="Port Hudson").wait_for(timeout=5000)
        assert page.locator("#panel .xq", has_text="Port Hudson").locator(".gen", has_text="you").count() == 1
        shot(page, "5-dig-and-add")
        # chat with no key: says how to set one, cites node ids, suggestions are buttons
        page.fill("#chatq", "What regiment did he enlist in?")
        page.click("#chatf button")
        page.wait_for_selector("#msgs a.cite", timeout=8000)
        assert "ANTHROPIC_API_KEY" in page.locator("#chatmode").inner_text()
        page.locator("#msgs .sugg").first.click()
        page.wait_for_function("[...document.querySelectorAll('#msgs .sugg')].some(b=>b.textContent.startsWith('Added')||b.textContent.startsWith('Already'))", timeout=5000)
        shot(page, "6-chat")
        assert child
        b.close()
