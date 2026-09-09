from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from agent_core import build_graph, last_ai_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

log = logging.getLogger("notion-mcp-api")

load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET")
ACCESS_EXPIRE_M = int(os.getenv("JWT_EXP_MIN", 30))

if not JWT_SECRET:
    raise RuntimeError("Missing required env var: JWT_SECRET")

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def create_jwt(subject: str) -> str:
    exp = datetime.utcnow() + timedelta(minutes=ACCESS_EXPIRE_M)
    return jwt.encode({"sub": subject, "exp": exp}, JWT_SECRET, algorithm=ALGORITHM)


def verify_jwt(token: str = Depends(oauth2_scheme)) -> str:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload["sub"]
    except (JWTError, KeyError):
        raise cred_exc


user_cred = {"arya": {"username": "arya", "password": "test123"}}


def authenticate(username: str, password: str) -> bool:
    user = user_cred.get(username)
    return bool(user and user["password"] == password)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    thread_id: str


app = FastAPI(
    title="Notion-MCP Agent API",
    version="1.0.0",
    description="JWT-protected API for NovaTech task management via Gemini + Notion MCP.",
)


@app.on_event("startup")
async def _startup():
    log.info("Building LangGraph agent …")
    app.state.graph = await build_graph()
    log.info("LangGraph agent ready.")


@app.post("/token", response_model=TokenOut, tags=["auth"])
async def login(form: OAuth2PasswordRequestForm = Depends()):
    if not authenticate(form.username, form.password):
        raise HTTPException(status_code=400, detail="Incorrect credentials")
    return {"access_token": create_jwt(form.username)}


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(req: ChatRequest, request: Request, user: str = Depends(verify_jwt)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    graph = request.app.state.graph
    thread_id = req.thread_id or str(uuid.uuid4())

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=req.message)]},
        config={"configurable": {"thread_id": thread_id}},
    )

    return ChatResponse(
        answer=last_ai_text(result["messages"]),
        thread_id=thread_id,
    )
