import asyncio
import unittest

from web import ai
from web.layout import LAYOUT_JS, main_chat, page
from web.sse import parse


class ChatUITests(unittest.TestCase):
    def test_main_chat_is_centered_without_copilot_rail(self):
        html = "".join(str(item) for item in page(
            "ai", "FastBI", "analyst@example.com", "thread-1", main_chat("thread-1")
        ))
        self.assertIn("Ask your data anything", html)
        self.assertIn("no-copilot", html)
        self.assertNotIn("Dashboard copilot", html)

    def test_copilot_is_only_mounted_on_dashboards(self):
        dashboard = "".join(str(item) for item in page(
            "dashboards", "FastBI", "analyst@example.com", "thread-1", "dashboard"
        ))
        sql = "".join(str(item) for item in page(
            "sqllab", "FastBI", "analyst@example.com", "thread-1", "sql"
        ))
        self.assertIn("Dashboard copilot", dashboard)
        self.assertIn("with-copilot", dashboard)
        self.assertNotIn("Dashboard copilot", sql)

    def test_stream_has_named_progress_token_and_done_events(self):
        async def collect():
            return [parse(chunk) async for chunk in ai.stream_chat("/help")]

        events = asyncio.run(collect())
        self.assertEqual([name for name, _ in events], ["progress", "progress", "token", "done"])
        self.assertIn("FastBI shortcuts", events[2][1]["token"])

    def test_browser_script_contains_progress_and_visual_handlers(self):
        self.assertIn("event.type==='progress'", LAYOUT_JS)
        self.assertIn("renderVisual", LAYOUT_JS)
        self.assertIn("new vis.Network", LAYOUT_JS)
        self.assertIn("Plotly.newPlot", LAYOUT_JS)


if __name__ == "__main__":
    unittest.main()
