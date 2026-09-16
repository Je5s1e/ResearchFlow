import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def digest(value):
    raw = value if isinstance(value, bytes) else json_text(value).encode()
    return hashlib.sha256(raw).hexdigest()


def safe_name(value, limit=90):
    value = re.sub(r"[^\w\- .\u4e00-\u9fff]", "_", value).strip(" ._")
    return value[:limit] or "untitled"


def atomic_write(path: Path, content: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:8])
    try:
        if isinstance(content, bytes):
            tmp.write_bytes(content)
        else:
            tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.on_event = None

    @classmethod
    def create(cls, root, request):
        sid = (
            datetime.now().strftime("%Y%m%d_%H%M%S")
            + "_"
            + safe_name(request, 22).replace(" ", "_")
            + "_"
            + uuid.uuid4().hex[:8]
        )
        store = cls(Path(root) / sid)
        store.path.mkdir(parents=True, exist_ok=False)
        for folder in ["papers", "texts", "notes", "artifacts", "logs/mcp", "cache"]:
            (store.path / folder).mkdir(parents=True, exist_ok=True)
        store.write_json("session.json", {"id": sid, "created_at": now(), "request": request})
        atomic_write(store.path / "request.md", request + "\n")
        return store

    def resolve(self, relative):
        path = (self.path / relative).resolve()
        if not path.is_relative_to(self.path):
            raise ValueError("产物路径不能离开会话目录")
        return path

    def read_json(self, relative):
        return json.loads(self.resolve(relative).read_text(encoding="utf-8"))

    def write_json(self, relative, value):
        atomic_write(self.resolve(relative), json_text(value) + "\n")
        return self.ref(relative)

    def ref(self, relative):
        return {"path": str(relative), "sha256": digest(self.resolve(relative).read_bytes())}

    def verify(self, refs):
        for ref in refs:
            p = self.resolve(ref["path"])
            if not p.is_file() or digest(p.read_bytes()) != ref["sha256"]:
                raise ValueError(f"产物缺失或被修改：{ref['path']}；不能使用旧审批，请恢复原文件。")

    def artifact(self, stem, suffix, content):
        folder = self.path / "artifacts"
        n = 1
        while (folder / f"{stem}.v{n}.{suffix}").exists():
            n += 1
        relative = f"artifacts/{stem}.v{n}.{suffix}"
        atomic_write(self.resolve(relative), content)
        return self.ref(relative), n

    def event(self, event_type, data, event_id=None):
        path = self.path / "logs/events.jsonl"
        if event_id and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if json.loads(line).get("event_id") == event_id:
                    return
        row = {"time": now(), "type": event_type, "event_id": event_id, **data}
        if self.on_event:
            self.on_event(row)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if event_type == "message":
            with (self.path / "logs/conversation.md").open("a", encoding="utf-8") as f:
                f.write(
                    f"\n## {row['time']} {data['sender']} → {data['receiver']}\n\n{data['content']}\n"
                )

    def audit_messages(self, state):
        for message in state.get("messages", []):
            self.event("message", message, message["id"])

    def status(self, stage, **extra):
        value = self.read_json("session.json")
        value.update(stage=stage, updated_at=now(), **extra)
        self.write_json("session.json", value)
