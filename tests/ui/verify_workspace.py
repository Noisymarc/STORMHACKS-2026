"""Replay the actual browser UI with simulated providers and an in-memory glossary.

Run with a Python environment containing Playwright. The owned server uses the
project's .venv and an ephemeral localhost port. No .env, cloud APIs or TiDB are used.
Artifacts are saved outside the repository, under the system temporary directory.
"""

import io
import asyncio
import json
import math
import os
from contextlib import contextmanager
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid
import wave

REPO = Path(__file__).resolve().parents[2]
EXPLANATION = "機会費用とは、何かを選ぶことで手放す、次に良い選択肢の価値です。例えば、授業に出るために仕事を休むと、得られたはずの賃金が機会費用になります。"
SOURCE = "Today we are studying opportunity cost. Choosing between work and class means giving up the benefits of the next best option."
TRANSLATION = "今日は機会費用を学びます。仕事と授業のどちらかを選ぶことは、次に良い選択肢から得られる利益を手放すことを意味します。"


def serve(port):
    """Serve the production HTML, CSS and explanation routes with fake providers."""
    sys.path.insert(0, str(REPO))
    from fastapi import FastAPI, HTTPException, WebSocket
    from backend import live_app as backend
    import uvicorn

    # Register public production handlers on a separate app; do not mutate
    # FastAPI's included-router internals to replace database routes.
    app = FastAPI()
    app.get("/")(backend.home)
    app.mount("/static", backend.StaticFiles(directory=REPO / "frontend"), name="static")
    app.post("/api/explain")(backend.explain_phrase)
    app.post("/api/explanation-audio")(backend.explanation_audio)
    app.post("/api/translate-transcript")(backend.translate_transcript)
    state = {"database_failure": False, "explanation_failure": False,
             "audio_failure": False, "explanation_calls": 0, "audio_calls": 0,
             "translation_failure": False, "translation_calls": 0}
    memories = {}
    connections = set()

    class FakeModels:
        async def generate_content(self, **kwargs):
            if kwargs["config"].response_mime_type != "application/json":
                state["translation_calls"] += 1
                await asyncio.sleep(0.4)
                if state["translation_failure"]:
                    error = RuntimeError("Simulated translation quota failure")
                    error.code = 429
                    raise error
                return backend.types.GenerateContentResponse(candidates=[backend.types.Candidate(
                    content=backend.types.Content(parts=[backend.types.Part(text=TRANSLATION)]),
                    finish_reason=backend.types.FinishReason.STOP,
                )])
            state["explanation_calls"] += 1
            if state["explanation_failure"]:
                error = RuntimeError("Simulated quota failure")
                error.code = 429
                raise error
            request = json.loads(kwargs["contents"])
            state["last_explanation_language"] = request["output_language"]
            return SimpleNamespace(text=json.dumps({"translation": "機会費用", "explanation": EXPLANATION}))

    class FakeSpeech:
        def convert(self, **kwargs):
            state["audio_calls"] += 1
            state["last_audio_language"] = kwargs["language_code"]

            async def chunks():
                if state["audio_failure"]:
                    raise RuntimeError("Simulated audio failure")
                # A short synthetic tone verifies media decoding, not speech quality.
                output = io.BytesIO()
                with wave.open(output, "wb") as audio:
                    audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    audio.writeframes(b"".join(struct.pack("<h", int(800 * math.sin(i * 2 * math.pi * 440 / 16000))) for i in range(3200)))
                yield output.getvalue()

            return chunks()

    backend.gemini_client = SimpleNamespace(aio=SimpleNamespace(models=FakeModels()))
    backend.elevenlabs_client = SimpleNamespace(text_to_speech=FakeSpeech())

    def user_memories(user_id):
        if state["database_failure"]:
            raise HTTPException(503, "Simulated glossary outage. Live captions still work.")
        return memories.setdefault(user_id, [{"id": "101", "phrase": "opportunity cost",
            "context": SOURCE, "translation": "機会費用", "explanation": EXPLANATION, "language": "Japanese"}])

    @app.get("/api/memories")
    async def list_memories(user_id: str, language: str):
        return {"memories": [entry for entry in user_memories(user_id) if entry["language"] == language]}

    @app.post("/api/memories")
    async def save_memory(body: dict):
        entries = user_memories(body["user_id"])
        existing = next((entry for entry in entries if entry["phrase"] == body["phrase"] and entry["language"] == body["language"]), None)
        if existing is None:
            existing = {"id": str(uuid.uuid4().int % (2**63 - 1) or 1)}
            entries.append(existing)
        existing.update({key: body[key] for key in ("phrase", "context", "translation", "explanation", "language")})
        return {"id": existing["id"]}

    @app.post("/api/memories/search")
    async def search_memories(body: dict):
        entries = user_memories(body["user_id"])
        found = [entry for entry in entries if entry["language"] == body["language"] and
                 (entry["phrase"] in body["transcript"].lower() or "next best" in body["transcript"].lower())]
        return {"memories": found}

    @app.delete("/api/memories/{memory_id}")
    async def remove_memory(memory_id: str, user_id: str):
        entries = user_memories(user_id)
        memories[user_id] = [entry for entry in entries if entry["id"] != memory_id]
        return {"forgotten": True}

    @app.websocket("/ws/continuous")
    async def simulated_speech(ws: WebSocket):
        await ws.accept()
        connections.add(ws)
        try:
            await ws.send_json({"type": "status", "message": "Simulated speech connection"})
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect" or message.get("text") == "stop":
                    break
        finally:
            connections.discard(ws)
            try:
                await ws.close()
            except RuntimeError:
                pass

    @app.post("/__ui/replay")
    async def replay(body: dict):
        if not connections:
            raise HTTPException(409, "No fixture listener")
        for ws in list(connections):
            await ws.send_json({"type": "status", "message": "Simulated lecture · browser verification"})
            for kind, key in (("source_delta", "source"), ("translation_delta", "translation")):
                if body.get(key):
                    await ws.send_json({"type": kind, "text": body[key]})
        if body.get("disconnect"):
            for ws in list(connections):
                await ws.close()
        return {"sent": True}

    @app.get("/__ui/state")
    async def fixture_state():
        return state

    @app.post("/__ui/state")
    async def configure_fixture(body: dict):
        for key in ("database_failure", "explanation_failure", "audio_failure", "translation_failure"):
            if key in body:
                state[key] = bool(body[key])
        return state

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def verify():
    from playwright.sync_api import sync_playwright

    out = Path(tempfile.gettempdir()) / ("codex-lecture-workspace-" + time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir()
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    python = REPO / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    log = (out / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen([str(python), str(Path(__file__).resolve()), "--serve", str(port)],
        cwd=REPO, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    report = {"source": "Simulated captions, AI text, synthetic audio tone and in-memory glossary; real frontend and FastAPI explanation routes", "checks": [], "console_errors": []}

    def passed(label):
        report["checks"].append(label)

    @contextmanager
    def browser_session():
        # Capture the failure while the browser connection is still usable.
        with sync_playwright() as playwright:
            try:
                yield playwright
            except Exception:
                try:
                    report["page_state"] = page.evaluate("""() => Object.fromEntries(
                      ['status', 'memory-status', 'memory-error', 'error', 'explanation-error']
                        .map(id => [id, document.getElementById(id)?.textContent]))""")
                    page.screenshot(path=str(out / "failure.png"), full_page=True)
                except Exception:
                    pass
                raise

    def select_phrase(page, phrase, selector="#source-caption"):
        page.evaluate("""({phrase, selector}) => {
          const container = document.querySelector(selector);
          const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
          const nodes = []; let node; let offset = 0;
          while (node = walker.nextNode()) { nodes.push({node, start: offset}); offset += node.textContent.length; }
          const start = container.textContent.indexOf(phrase);
          if (start < 0) throw new Error('Fixture phrase not found');
          const end = start + phrase.length;
          const first = nodes.find(entry => start >= entry.start && start < entry.start + entry.node.length);
          const last = nodes.find(entry => end > entry.start && end <= entry.start + entry.node.length);
          const range = document.createRange();
          range.setStart(first.node, start - first.start); range.setEnd(last.node, end - last.start);
          window.getSelection().removeAllRanges(); window.getSelection().addRange(range);
          document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        }""", {"phrase": phrase, "selector": selector})

    try:
        with browser_session() as playwright:
            base = f"http://127.0.0.1:{port}"
            api = playwright.request.new_context(base_url=base)
            for _ in range(60):
                try:
                    if api.get("/__ui/state", timeout=1000).ok:
                        break
                except Exception:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Fixture server failed to start; inspect server.log")
            browser = playwright.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
            context = browser.new_context(viewport={"width": 1440, "height": 1040}, permissions=["microphone"])
            page = context.new_page()
            page.on("pageerror", lambda error: report["console_errors"].append(str(error)))
            page.goto(base)
            page.wait_for_function("document.querySelector('#memory-status').textContent.includes('1 saved')")
            assert page.locator("#explanation-language").input_value() == "Japanese"
            assert page.locator("#explain-button").is_disabled()
            assert api.get("/static/live.css").ok
            assert api.get("/static/missing.css").status == 404
            passed("CSS served; Japanese default; empty-selection action disabled; missing asset returns 404")
            tokens = page.evaluate("""() => {
              const style = getComputedStyle(document.documentElement);
              return Object.fromEntries(['text', 'surface', 'text-secondary', 'surface-soft',
                'accent', 'accent-hover', 'accent-soft', 'error', 'error-surface']
                .map(name => [name, style.getPropertyValue('--' + name).trim()]));
            }""")
            pairs = ((tokens['text'], tokens['surface']), (tokens['text-secondary'], tokens['surface-soft']),
                     ('#ffffff', tokens['accent']), (tokens['accent-hover'], tokens['accent-soft']),
                     (tokens['error'], tokens['error-surface']))
            def luminance(color):
                channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
                channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
                return sum(c * weight for c, weight in zip(channels, (0.2126, 0.7152, 0.0722)))
            for foreground, background in pairs:
                values = sorted((luminance(foreground), luminance(background)))
                assert (values[1] + 0.05) / (values[0] + 0.05) >= 4.5
            passed("Primary, supporting, action, highlighted-term and error text color pairs meet 4.5:1 contrast")
            page.keyboard.press("Tab")
            assert page.locator(".skip-link").evaluate("node => node === document.activeElement")
            page.keyboard.press("Enter")
            assert page.locator("#lecture").evaluate("node => node === document.activeElement")
            passed("Keyboard skip link reaches the lecture")

            page.locator("#start-button").click()
            page.wait_for_function("!document.querySelector('#stop-button').disabled")
            assert api.post("/__ui/replay", data={"source": SOURCE, "translation": TRANSLATION}).ok
            page.locator("#source-caption button").first.wait_for()
            page.wait_for_function("document.querySelector('#memory-matches').textContent.includes('Possibly related')")
            assert not page.locator("#memory-error").inner_text()
            passed("Fixture semantic suggestion is labeled Possibly related and has Japanese help without a glossary error")
            page.locator("#explanation-language").select_option("French")
            page.wait_for_function("document.querySelector('#memory-status').textContent.includes('0 saved')")
            assert page.locator("#translated-caption").inner_text() == TRANSLATION
            assert page.locator("#translated-caption").get_attribute("lang") == "ja"
            page.locator("#explanation-language").select_option("Japanese")
            page.wait_for_function("document.querySelector('#memory-status').textContent.includes('1 saved')")
            passed("Changing help language leaves live Japanese captions unchanged; switching back restores Japanese glossary")
            select_phrase(page, "Choosing between")
            assert page.locator("#selected-phrase").inner_text() == "None"
            saved = page.locator("#source-caption button").first
            saved.focus()
            focused_key = saved.get_attribute("data-glossary-key")
            assert api.post("/__ui/replay", data={"source": " We now compare the next best alternative."}).ok
            page.wait_for_function("document.querySelector('#source-caption').textContent.includes('We now')")
            assert page.evaluate("document.activeElement.dataset.glossaryKey") == focused_key
            assert page.locator("#memory-matches").inner_text().find("機会費用") >= 0
            passed("Streaming exact terms are keyboard accessible; focus survives updates; new selection blocked while listening")

            long_source = " We briefly hold details in mind while considering an alternative." * 90
            long_translation = "選択肢を比べるときには、情報を短時間覚えながら考えます。" * 100
            page.locator("#stop-button").focus()
            assert api.post("/__ui/replay", data={"source": long_source, "translation": long_translation}).ok
            page.wait_for_function("document.querySelector('#translated-caption').textContent.length > 1500")
            page.wait_for_function("document.querySelector('#translation-scroll').scrollTop > 0")
            page.locator("#translation-scroll").evaluate("node => node.scrollTop = 0")
            page.locator("#translation-jump").wait_for(state="visible")
            assert api.post("/__ui/replay", data={"translation": "新しい内容が届いても、読んでいる位置は変わりません。"}).ok
            page.wait_for_function("document.querySelector('#translated-caption').textContent.endsWith('変わりません。')")
            assert page.locator("#translation-scroll").evaluate("node => node.scrollTop") < 4
            page.locator("#translation-jump").click()
            page.wait_for_function("(() => {const v=document.querySelector('#translation-scroll'); return v.scrollHeight-v.scrollTop-v.clientHeight < 5;})()")
            assert page.locator("#translation-jump").evaluate("node => node === document.activeElement && !node.hidden")
            page.keyboard.press("Tab")
            page.locator("#translation-jump").wait_for(state="hidden")
            passed("Caption pane follows new text, preserves reading position, and Jump to live retains focus then hides on blur")

            for width in (375, 768, 1024, 1440):
                page.set_viewport_size({"width": width, "height": 1040})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"Horizontal overflow at {width}px"
                assert page.locator("#translation-scroll").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
                assert page.locator("#transcript-scroll").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
                page.screenshot(path=str(out / f"streaming-{width}.png"), full_page=True)
            assert not page.locator("#memory-error").inner_text()
            page.emulate_media(reduced_motion="reduce")
            assert page.locator("#start-button").evaluate("node => getComputedStyle(node).transitionDuration") == "0s"
            passed("Long Japanese and English captions wrap at 375, 768, 1024 and 1440px; reduced motion disables transitions")

            page.locator("#stop-button").click()
            page.wait_for_function("!document.querySelector('#start-button').disabled")
            select_phrase(page, "opportunity cost")
            assert page.locator("#selected-phrase").inner_text() == "opportunity cost"
            page.locator("#explain-button").click()
            page.locator("#explanation-audio").wait_for(state="visible")
            page.wait_for_function("document.querySelector('#memory-status').textContent.includes('saved to your glossary')")
            assert page.locator("#explanation-text").inner_text() == EXPLANATION
            provider_state = api.get("/__ui/state").json()
            assert provider_state["last_explanation_language"] == "Japanese" and provider_state["last_audio_language"] == "ja"
            assert page.locator("#explanation-audio").evaluate("node => node.readyState >= 1")
            passed("Stopped transcript selection generates Japanese explanation, saves it and decodes fixture audio; provider language arguments match")
            page.locator("#explain-button").click()
            page.wait_for_function("!document.querySelector('#explain-button').disabled")
            assert api.get("/__ui/state").json()["explanation_calls"] == 1
            passed("Repeated explanation reuses cached text and audio")

            select_phrase(page, "Choosing between")
            api.post("/__ui/state", data={"explanation_failure": True})
            page.locator("#explain-button").click()
            page.wait_for_function("document.querySelector('#explanation-error').textContent.includes('usage limit')")
            assert page.locator("#explain-button").is_enabled() and page.locator("#start-button").is_enabled()
            passed("Simulated AI quota failure appears beside explanation and restores retry controls")
            api.post("/__ui/state", data={"explanation_failure": False, "audio_failure": True})
            page.locator("#explain-button").click()
            page.wait_for_function("document.querySelector('#explanation-status').textContent.includes('retry the audio')")
            assert page.locator("#explanation-text").inner_text() == EXPLANATION
            api.post("/__ui/state", data={"audio_failure": False})
            page.locator("#explain-button").click()
            page.locator("#explanation-audio").wait_for(state="visible")
            passed("Speech failure leaves Japanese text usable; retry requests audio without regenerating explanation")

            page.reload()
            page.wait_for_function("document.querySelector('#memory-status').textContent.includes('2 saved')")
            page.locator("#glossary-library > summary").click()
            assert "機会費用" in page.locator("#glossary-list").inner_text()
            page.locator("#glossary-list .remove-button").last.click()
            page.wait_for_function("document.querySelector('#glossary-list').children.length === 1")
            page.locator("#glossary-library > summary").click()
            passed("Fixture glossary persists across refresh and Remove updates its list")

            page.locator("#start-button").click()
            page.wait_for_function("!document.querySelector('#stop-button').disabled")
            api.post("/__ui/replay", data={"source": SOURCE, "translation": TRANSLATION})
            page.locator("#source-caption button").first.wait_for()
            page.locator("#stop-button").click()
            page.wait_for_function("!document.querySelector('#start-button').disabled")
            select_phrase(page, "opportunity cost")
            page.locator("#explain-button").click()
            page.locator("#explanation-audio").wait_for(state="visible")
            page.wait_for_function("!document.querySelector('#explain-button').disabled")
            # Keep the captured preview visibly labeled as sample data.
            page.locator("#status").evaluate("node => node.textContent = 'Simulated lecture · browser verification'")
            page.screenshot(path=str(out / "workspace-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 375, "height": 900})
            page.screenshot(path=str(out / "workspace-mobile.png"), full_page=True)

            api.post("/__ui/state", data={"database_failure": True})
            page.reload()
            page.wait_for_function("document.querySelector('#memory-status').textContent.includes('unavailable')")
            page.locator("#start-button").click()
            page.wait_for_function("!document.querySelector('#stop-button').disabled")
            api.post("/__ui/replay", data={"source": SOURCE, "translation": TRANSLATION})
            page.wait_for_function("document.querySelector('#translated-caption').textContent.includes('機会費用')")
            assert page.locator("#memory-error").inner_text()
            passed("Simulated database failure does not block captions")
            api.post("/__ui/replay", data={"disconnect": True})
            page.wait_for_function("!document.querySelector('#start-button').disabled")
            assert page.locator("#error").inner_text() and "機会費用" in page.locator("#translated-caption").inner_text()
            passed("Caption disconnect preserves text and restores microphone controls")

            api.post("/__ui/state", data={"database_failure": False, "explanation_failure": False, "audio_failure": False})
            page.reload()
            page.wait_for_function("document.querySelector('#memory-status').textContent.includes('saved')")
            page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {
                configurable: true, value: {readText: async () => {throw new DOMException('Blocked', 'NotAllowedError');}}
            })""")
            page.locator("#paste-transcript-button").click()
            page.wait_for_function("document.querySelector('#transcript-import-status').textContent.includes('Ctrl+V')")
            assert page.locator("#transcript-input").evaluate("node => node === document.activeElement")
            assert page.locator("#translate-transcript-button").is_disabled()
            passed("Paste opens a labeled editor; blocked clipboard access permits manual paste; empty input cannot submit")

            page.evaluate("""() => {navigator.clipboard.readText = () => new Promise(resolve => {window.resolvePendingPaste = resolve;});}""")
            page.locator("#paste-transcript-button").click()
            page.locator("#transcript-input").fill("New text typed while clipboard permission was pending.")
            page.evaluate("async () => {window.resolvePendingPaste('Old clipboard text'); await Promise.resolve();}")
            assert page.locator("#transcript-input").input_value() == "New text typed while clipboard permission was pending."
            passed("A delayed clipboard response cannot overwrite newer manual input")

            page.evaluate("""text => {navigator.clipboard.readText = async () => text;}""", SOURCE)
            page.locator("#paste-transcript-button").click()
            page.wait_for_function("text => document.querySelector('#transcript-input').value === text", arg=SOURCE)
            page.locator("#translate-transcript-button").click()
            assert page.locator("#start-button").is_disabled()
            assert page.locator("#translate-transcript-button").is_disabled()
            page.wait_for_function("document.querySelector('#status').textContent.includes('Transcript translated')")
            assert page.locator("#source-caption").inner_text() == SOURCE
            assert page.locator("#translated-caption").inner_text() == TRANSLATION
            assert api.get("/__ui/state").json()["translation_calls"] == 1
            select_phrase(page, "opportunity cost")
            page.locator("#explain-button").click()
            page.wait_for_function("document.querySelector('#explanation-status').textContent.includes('Explanation ready')")
            assert "機会費用" in page.locator("#explanation-text").inner_text()
            passed("Clipboard transcript translates through the actual handler; duplicate submission is blocked; phrase explanations remain usable")

            page.locator("#paste-transcript-button").click()
            page.locator("#transcript-file").set_input_files({"name": "lecture.txt", "mimeType": "text/plain", "buffer": SOURCE.encode("utf-8")})
            page.wait_for_function("document.querySelector('#transcript-import-status').textContent.includes('lecture.txt loaded')")
            page.locator("#translate-transcript-button").click()
            page.wait_for_function("document.querySelector('#transcript-import').hidden")
            assert api.get("/__ui/state").json()["translation_calls"] == 2
            passed("UTF-8 .txt upload loads the full text and translates into the reading panes")

            page.locator("#paste-transcript-button").click()
            page.locator("#transcript-input").fill("This replacement transcript should be retained after a provider failure.")
            api.post("/__ui/state", data={"translation_failure": True})
            page.locator("#translate-transcript-button").click()
            page.wait_for_function("document.querySelector('#transcript-import-error').textContent.includes('usage limit')")
            assert page.locator("#source-caption").inner_text() == SOURCE
            assert "replacement transcript" in page.locator("#transcript-input").input_value()
            assert page.locator("#translate-transcript-button").is_enabled()
            passed("Translation quota failure preserves editable input and previous captions and enables retry")

            for name, data, error_text in (
                ("lecture.pdf", b"not a text file", "UTF-8 .txt"),
                ("lecture.txt", b"", "some text"),
                ("lecture.txt", b"\xff\xfe", "UTF-8 plain text"),
                ("lecture.txt", b"a" * 100001, "100 KB"),
            ):
                page.locator("#transcript-file").set_input_files({"name": name, "mimeType": "text/plain", "buffer": data})
                page.wait_for_function("text => document.querySelector('#transcript-import-error').textContent.includes(text)", arg=error_text)
                assert "replacement transcript" in page.locator("#transcript-input").input_value()
            page.locator("#transcript-input").fill("a" * 20001)
            assert len(page.locator("#transcript-input").input_value()) == 20001
            assert "20,000" in page.locator("#transcript-import-error").inner_text()
            assert page.locator("#translate-transcript-button").is_disabled()
            passed("Invalid, empty, non-UTF-8 and oversized uploads are rejected; overlong paste is retained rather than truncated")

            page.locator("#transcript-input").fill(SOURCE)
            page.set_viewport_size({"width": 375, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
            page.locator("#status").evaluate("node => node.textContent = 'Simulated transcript · browser verification'")
            page.screenshot(path=str(out / "transcript-editor-mobile.png"), full_page=True)
            page.locator("#close-transcript-button").click()
            assert page.locator("#paste-transcript-button").evaluate("node => node === document.activeElement")
            page.locator("#start-button").click()
            page.wait_for_function("!document.querySelector('#stop-button').disabled")
            assert page.locator("#paste-transcript-button").is_disabled()
            page.locator("#stop-button").click()
            page.wait_for_function("!document.querySelector('#paste-transcript-button').disabled")
            passed("Transcript editor fits mobile, returns focus when closed and cannot replace an active microphone session")
            assert not report["console_errors"], report["console_errors"]
            passed("No uncaught browser exceptions")
            context.close()
            browser.close()
            api.dispose()
    except Exception as error:
        report["failure"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
        print(json.dumps({"artifacts": str(out), "passed_checks": len(report["checks"]), "failure": report.get("failure")}, ensure_ascii=True))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(int(sys.argv[2]))
    else:
        verify()
