"""HTTP API аккаунтов Session Controller."""

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import time
from collections import deque
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
    name TEXT NOT NULL, avatar TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tokens (
    hash TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
    service TEXT NOT NULL, fields TEXT NOT NULL
);
"""

Text = Annotated[str, Field(min_length=1, max_length=80)]
bearer = HTTPBearer(auto_error=False)


class LimitBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT"}:
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message["body"]
            if len(body) + len(chunk) > 160_000:
                response = JSONResponse({"detail": "Запрос слишком большой."}, status_code=413)
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        async def replay():
            nonlocal body
            if body is None:
                return await receive()
            message = {"type": "http.request", "body": bytes(body), "more_body": False}
            body = None
            return message

        await self.app(scope, replay, send)


class Login(BaseModel):
    login: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{3,32}$")]
    password: Annotated[str, Field(min_length=8, max_length=128)]


class Profile(BaseModel):
    name: Text
    avatar: Annotated[str, Field(max_length=100_000)] = ""


class EntryField(BaseModel):
    label: Text
    value: Annotated[str, Field(max_length=1000)] = ""
    secret: bool = False


class Entry(BaseModel):
    service: Text
    fields: Annotated[list[EntryField], Field(min_length=1, max_length=20)]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str, salt: bytes) -> str:
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 << 20)
    return f"{salt.hex()}:{key.hex()}"


def database_path() -> Path:
    override = os.environ.get("SC_ACCOUNT_DB") or os.environ.get("SC_DEMO_DB")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    database = base / "SessionControllerAccounts" / "accounts.sqlite3"
    existing = base / "SessionControllerDemo" / "demo.sqlite3"
    return existing if not database.exists() and existing.is_file() else database


@contextmanager
def database(path: Path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with database(path) as db:
        db.executescript(SCHEMA)


def create_app(path: Path) -> FastAPI:
    initialize(path)
    app = FastAPI(title="Session Controller Accounts", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LimitBody)
    attempts: deque[float] = deque()
    attempts_lock = Lock()
    fallback_hash = password_hash("invalid", secrets.token_bytes(16))

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def limit_auth() -> None:
        with attempts_lock:
            now = time.monotonic()
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= 20:
                raise HTTPException(429, "Слишком много попыток. Попробуй через минуту.")
            attempts.append(now)

    def authorized(auth: HTTPAuthorizationCredentials | None = Depends(bearer)) -> tuple[str, str]:
        if auth and len(auth.credentials) <= 128:
            token_hash = digest(auth.credentials)
            with database(path) as db:
                row = db.execute(
                    "SELECT owner FROM tokens WHERE hash=? AND (expires=0 OR expires>?)",
                    (token_hash, time.time()),
                ).fetchone()
            if row:
                return row["owner"], token_hash
        raise HTTPException(401, "Войди в аккаунт снова.")

    @app.get("/health")
    def health():
        return {"service": "session-controller-accounts"}

    @app.post("/register", status_code=201, dependencies=[Depends(limit_auth)])
    def register(data: Login):
        login = data.login.lower()
        hashed = password_hash(data.password, secrets.token_bytes(16))
        try:
            with database(path) as db:
                db.execute(
                    "INSERT INTO users (id, login, password, name) VALUES (?, ?, ?, ?)",
                    (uuid4().hex, login, hashed, data.login),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Этот логин уже занят.") from exc
        return {"registered": True}

    @app.post("/login", dependencies=[Depends(limit_auth)])
    def login(data: Login):
        with database(path) as db:
            user = db.execute("SELECT id, password FROM users WHERE login=?", (data.login.lower(),)).fetchone()
            expected = user["password"] if user else fallback_hash
            salt = bytes.fromhex(expected.split(":", 1)[0])
            if not hmac.compare_digest(password_hash(data.password, salt), expected) or not user:
                raise HTTPException(401, "Неверный логин или пароль.")
            token = secrets.token_urlsafe(32)
            now = int(time.time())
            db.execute("DELETE FROM tokens WHERE expires>0 AND expires<=?", (now,))
            # Новая сессия сохраняется между запусками клиента до выхода.
            db.execute("INSERT INTO tokens VALUES (?, ?, 0)", (digest(token), user["id"]))
        return {"token": token}

    @app.post("/logout", status_code=204)
    def logout(identity=Depends(authorized)):
        with database(path) as db:
            db.execute("DELETE FROM tokens WHERE hash=?", (identity[1],))
        return Response(status_code=204)

    @app.get("/profile")
    def profile(identity=Depends(authorized)):
        with database(path) as db:
            return dict(db.execute(
                "SELECT id, login, name, avatar FROM users WHERE id=?", (identity[0],)
            ).fetchone())

    @app.put("/profile")
    def update_profile(data: Profile, identity=Depends(authorized)):
        if data.avatar:
            try:
                picture = base64.b64decode(data.avatar, validate=True)
            except ValueError as exc:
                raise HTTPException(400, "Некорректная аватарка.") from exc
            if len(picture) < 33 or not picture.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"):
                raise HTTPException(400, "Аватарка должна быть в формате PNG.")
            width, height = struct.unpack_from(">II", picture, offset=16)
            if not (1 <= width <= 96 and 1 <= height <= 96):
                raise HTTPException(400, "Размер аватарки должен быть до 96 × 96 пикселей.")
        name = data.name.strip()
        if not name:
            raise HTTPException(400, "Укажи имя профиля.")
        with database(path) as db:
            db.execute("UPDATE users SET name=?, avatar=? WHERE id=?", (name, data.avatar, identity[0]))
        return profile(identity)

    @app.get("/entries")
    def list_entries(identity=Depends(authorized)):
        with database(path) as db:
            rows = db.execute(
                "SELECT id, service FROM entries WHERE owner=? ORDER BY service COLLATE NOCASE, id",
                (identity[0],),
            )
            return [dict(row) for row in rows]

    @app.get("/entries/{entry_id}")
    def read_entry(entry_id: str, identity=Depends(authorized)):
        with database(path) as db:
            row = db.execute(
                "SELECT id, service, fields FROM entries WHERE id=? AND owner=?", (entry_id, identity[0])
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Запись не найдена.")
        return {"id": row["id"], "service": row["service"], "fields": json.loads(row["fields"])}

    def entry_values(data: Entry) -> tuple[str, str]:
        if not data.service.strip() or any(not item.label.strip() for item in data.fields):
            raise HTTPException(400, "Укажи название сервиса и названия всех полей.")
        return data.service.strip(), json.dumps([item.model_dump() for item in data.fields], ensure_ascii=False)

    @app.post("/entries", status_code=201)
    def create_entry(data: Entry, identity=Depends(authorized)):
        entry_id = uuid4().hex
        service, fields = entry_values(data)
        with database(path) as db:
            db.execute("INSERT INTO entries VALUES (?, ?, ?, ?)", (entry_id, identity[0], service, fields))
        return {"id": entry_id}

    @app.put("/entries/{entry_id}")
    def update_entry(entry_id: str, data: Entry, identity=Depends(authorized)):
        service, fields = entry_values(data)
        with database(path) as db:
            result = db.execute(
                "UPDATE entries SET service=?, fields=? WHERE id=? AND owner=?",
                (service, fields, entry_id, identity[0]),
            )
            if not result.rowcount:
                raise HTTPException(404, "Запись не найдена.")
        return {"id": entry_id}

    @app.delete("/entries/{entry_id}", status_code=204)
    def delete_entry(entry_id: str, identity=Depends(authorized)):
        with database(path) as db:
            if not db.execute(
                "DELETE FROM entries WHERE id=? AND owner=?", (entry_id, identity[0])
            ).rowcount:
                raise HTTPException(404, "Запись не найдена.")
        return Response(status_code=204)

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Сервис аккаунтов Session Controller")
    parser.add_argument("command", choices=["serve"])
    parser.parse_args()
    uvicorn.run(create_app(database_path()), host="127.0.0.1", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main()
