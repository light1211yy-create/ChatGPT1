"""Local HTTP/WebSocket UI smoke test, own server and temporary DB only."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tornado.httpclient import HTTPRequest
from tornado.websocket import websocket_connect
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from studio.db import Store
from studio.research import ResearchStore


class BrowserProtocol:
    def __init__(self, ws):
        self.ws, self.states, self.elements = ws, {}, []

    def element(self, kind, label, index=0):
        return [getattr(e, kind) for e in self.elements if e.HasField(kind) and getattr(e, kind).label == label][index]

    async def render(self, changes=()):
        trigger_ids = []
        for element, field, value in changes:
            self.states[element.id] = (field, value)
            if field == "trigger_value": trigger_ids.append(element.id)
        back = BackMsg()
        back.rerun_script.query_string = ""
        for identifier, (field, value) in self.states.items():
            widget = back.rerun_script.widget_states.widgets.add()
            widget.id = identifier
            setattr(widget, field, value)
        await self.ws.write_message(back.SerializeToString(), binary=True)
        for identifier in trigger_ids: self.states.pop(identifier)
        elements = []
        for _ in range(500):
            raw = await asyncio.wait_for(self.ws.read_message(), timeout=20)
            assert raw is not None, "Server disconnected"
            message = ForwardMsg()
            message.ParseFromString(raw)
            if message.HasField("delta"):
                element = message.delta.new_element
                assert not element.HasField("exception"), "Application exception in live UI"
                elements.append(element)
            if message.HasField("script_finished"):
                if message.script_finished == ForwardMsg.FINISHED_SUCCESSFULLY:
                    self.elements = elements
                    return
                assert message.script_finished == ForwardMsg.FINISHED_EARLY_FOR_RERUN
                elements = []
        raise AssertionError("Render did not finish")

    async def page(self, index):
        radio = self.element("radio", "メニュー")
        await self.render([(radio, "int_value", index)])

    async def submit(self, label, values=()):
        changes = [(self.element(kind, name), field, value) for kind, name, field, value in values]
        changes.append((self.element("button", label), "trigger_value", True))
        await self.render(changes)


async def exercise(port, db, create):
    address = f"http://127.0.0.1:{port}"
    for path in ("/_stcore/health", "/"):
        with urllib.request.urlopen(address + path, timeout=10) as response:
            assert response.status == 200
    ws = await websocket_connect(HTTPRequest(f"ws://127.0.0.1:{port}/_stcore/stream", headers={"Origin":address}), subprotocols=["streamlit"])
    client = BrowserProtocol(ws)
    store = Store(db)
    try:
        await client.render()
        assert any("ダッシュボード" in str(e) for e in client.elements)
        if create:
            await client.page(1)
            assert any("AIモデルには接続していません" in str(e) for e in client.elements)
            await client.submit("テーマ10案を作成")
            assert len(store.themes()) == 10
            await client.submit("承認")
            approved = next(t for t in store.themes() if t["status"] == "承認")
            assert len(store.audit(approved["id"])) == 1
            await client.page(2)
            await client.submit("進捗を保存", [("selectbox","制作進捗","string_value","編集"),
                ("text_area","制作メモ","string_value","実サーバーから保存")])
            assert next(t for t in store.themes() if t["id"] == approved["id"])["progress"] == "編集"
            await client.page(4)
            for name in ("QA施設A", "QA施設B"):
                await client.submit("施設候補を登録", [("text_input","施設名","string_value",name),
                    ("text_input","住所","string_value","テスト用住所"),
                    ("text_input","施設公式URL","string_value","https://example.com/facility"),
                    ("text_area","施設情報・アクセス・営業時間","string_value","駅から徒歩5分（QA用）"),
                    ("text_area","料金と条件（任意）","string_value","2名・税込・参考価格（QA用）")])
            research = ResearchStore(store)
            assert len(research.facilities(approved["id"])) == 2
            fid = research.facilities(approved["id"])[0]["id"]
            await client.submit("出典を保存", [("text_input","確認項目","string_value","営業時間"),
                ("text_area","確認した情報","string_value","10〜18時"),
                ("text_input","出典URL","string_value","https://example.com/hours")])
            assert len(research.sources(fid)) == 1
            await client.submit("写真候補を保存", [("text_input","写真名","string_value","外観（QA）"),
                ("text_input","写真候補・掲載元URL","string_value","https://example.com/photo"),
                ("text_input","権利者","string_value","QA撮影者"),
                ("selectbox","利用許諾状況","string_value","利用可"),
                ("text_area","許諾の根拠","string_value","テスト用の根拠"),
                ("text_area","許諾された用途","string_value","商用SNS・加工可（QA）")])
            assert len(research.usable_photos(fid)) == 1
            await client.page(3)
            await client.submit("実績を登録", [("text_input","投稿タイトル","string_value","QAの投稿"),
                ("number_input","再生数","double_value",1000),
                ("number_input","いいね数","double_value",100),
                ("number_input","保存数","double_value",20)])
            assert len(store.performance()) == 1
        else:
            assert len(store.themes()) == 10 and len(store.performance()) == 1
            approved = next(t for t in store.themes() if t["status"] == "承認")
            assert approved["progress"] == "編集"
            await client.page(4)
            research = ResearchStore(store)
            assert len(research.facilities(approved["id"])) == 2
            fid = research.facilities(approved["id"])[0]["id"]
            assert len(research.sources(fid)) == len(research.photos(fid)) == 1
        await client.page(0)
    finally:
        ws.close()


def main():
    with tempfile.TemporaryDirectory(prefix="makase-live-qa-") as temp:
        database = Path(temp) / "live.sqlite3"
        for create in (True, False):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            run_env = os.environ.copy()
            run_env["MAKASE_DB_PATH"] = str(database)
            with open(Path(temp) / "server.log", "w+") as log:
                process = subprocess.Popen([sys.executable,"-m","streamlit","run","app.py","--server.address","127.0.0.1", "--server.port",str(port),"--server.headless","true","--browser.gatherUsageStats","false"], cwd=ROOT, env=run_env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    for _ in range(50):
                        assert process.poll() is None, "Temporary QA server stopped"
                        try:
                            with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health",timeout=1): break
                        except OSError:
                            time.sleep(0.2)
                    else:
                        raise AssertionError("Temporary QA server did not start")
                    asyncio.run(exercise(port, database, create))
                finally:
                    process.terminate()
                    process.wait(timeout=10)
            print("Live creation and 5-page navigation: PASS" if create else "Actual server restart persistence: PASS")
    print("Temporary DB only; test servers stopped; external AI/Canva/TikTok not called")


if __name__ == "__main__":
    main()
