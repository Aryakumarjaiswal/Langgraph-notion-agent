"""Shared Notion task-manager agent (Gemini + Notion MCP)."""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from gemini_chat import GeminiChat, SIG_KEY
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

warnings.filterwarnings("ignore", message=".*google.generativeai.*")

# _HERE = Path(__file__).resolve().parent
# for env_path in (_HERE.parent / ".env", _HERE / ".env"):
#     if env_path.exists():
#         load_dotenv(env_path, override=True)




GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL")
NOTION_MCP_TOKEN = os.getenv("NOTION_MCP_TOKEN")
NOTION_VERSION = os.getenv("NOTION_VERSION")
EMPLOYEES_DATABASE_ID = os.getenv("EMPLOYEES_DATABASE_ID")
TASKS_DATABASE_ID = os.getenv("TASKS_DATABASE_ID")

# if GEMINI_API_KEY:
#     os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY
#     os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

TASK_TOOLS = {
    "API-post-search",
    "API-query-data-source",
    "API-retrieve-a-data-source",
    "API-retrieve-a-database",
    "API-retrieve-a-page",
    "API-patch-page",
    "API-post-page",
    "API-retrieve-a-page-property",
}


def build_system_prompt(tool_names: list[str]) -> str:
    names = ", ".join(tool_names) if tool_names else "(none loaded)"
    return f"""You are a project task manager for the NovaTech client.

Your job is to create, update, list, and explain employee tasks stored in Notion.

Use these Notion databases only:
- Employees database id: {EMPLOYEES_DATABASE_ID}
- Tasks database id: {TASKS_DATABASE_ID}

Employees fields: Name, Email, Role, Team, Employment, Status
Tasks fields: Task, Assignee (relation to Employees), Status, Priority, Due date, Project, Estimate hours, Notes

Task Status values: To do, In progress, Done, Blocked
Priority values: Low, Medium, High, Urgent

Available Notion tools (copy these names exactly, including the API- prefix):
{names}

How to summarize databases:
1. Use API-post-search to find databases, OR
2. Use API-retrieve-a-database with database_id for Employees and Tasks, OR
3. Use API-query-data-source / API-retrieve-a-data-source if those tools exist.
Never invent a tool name like retrieve_a_database. If a tool fails, try another name from the list above.

Rules:
1. Prefer Notion tools for any create / update / search / list action.
2. When assigning work, find the employee in the Employees database, then set the Tasks Assignee relation.
3. Before a write (create or update), briefly say what you will change, then do it, then confirm what changed.
4. If a name, task, or field is unclear, ask one short question.
5. Keep answers short and clear. Use simple English.
6. Do not invent tasks or people that are not in Notion.
7. After you use tools, you MUST write a short text answer. Never finish with an empty message.
8. Only call tools that appear in the list above.
"""


async def build_graph():
    if not GEMINI_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY) in .env")
    if not NOTION_MCP_TOKEN:
        raise RuntimeError("Missing NOTION_MCP_TOKEN in .env")
    if not EMPLOYEES_DATABASE_ID or not TASKS_DATABASE_ID:
        raise RuntimeError("Missing EMPLOYEES_DATABASE_ID or TASKS_DATABASE_ID in .env")

    notion_cfg = {
        "notion": {
            "command": "npx",
            "args": ["-y", "@notionhq/notion-mcp-server"],
            "transport": "stdio",
            "env": {
                "OPENAPI_MCP_HEADERS": json.dumps(
                    {
                        "Authorization": f"Bearer {NOTION_MCP_TOKEN}",
                        "Notion-Version": NOTION_VERSION,
                    }
                )
            },
        }
    }

    print("Starting Notion MCP (first run can take 1-2 minutes)...", flush=True)
    client = MultiServerMCPClient(notion_cfg)
    all_tools = await client.get_tools()
    #print(all_tools)
    notion_tools = [
        tool
        for tool in all_tools
        if getattr(tool, "name", "") in TASK_TOOLS
    ] or all_tools
    tool_names = [getattr(t, "name", str(t)) for t in notion_tools]
    print(
        f"Notion MCP ready. Using {len(notion_tools)} task tools: {tool_names}",
        flush=True,
    )

    print(
        f"Using Gemini model={GEMINI_MODEL}, key starts with {GEMINI_API_KEY[:4]!r}, length={len(GEMINI_API_KEY)}",
        flush=True,
    )
    llm = GeminiChat(
        model=GEMINI_MODEL,
        api_key=GEMINI_API_KEY,
        temperature=0,
    )
    llm_with_tools = llm.bind_tools(notion_tools)

    def remap_tool_calls(ai_msg: AIMessage) -> AIMessage:
        calls = list(getattr(ai_msg, "tool_calls", None) or [])
        if not calls:
            return ai_msg
        known = set(tool_names)
        fixed = []
        changed = False
        for call in calls:
            name = call.get("name", "")
            if name in known:
                fixed.append(call)
                continue
            guesses = [
                name.replace("_", "-"),
                f"API-{name.replace('_', '-')}",
                f"API-{name}",
            ]
            match = next((g for g in guesses if g in known), None)
            if match:
                call = {**call, "name": match}
                changed = True
            fixed.append(call)
        if not changed:
            return ai_msg
        extra = dict(getattr(ai_msg, "additional_kwargs", None) or {})
        extra.setdefault(SIG_KEY, extra.get(SIG_KEY) or [])
        return AIMessage(
            content=ai_msg.content,
            tool_calls=fixed,
            additional_kwargs=extra,
            response_metadata=getattr(ai_msg, "response_metadata", {}) or {},
            id=getattr(ai_msg, "id", None),
        )

    system = SystemMessage(content=build_system_prompt(tool_names))

    async def agent_node(state: MessagesState):
        msgs = list(state["messages"])
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [system] + [m for m in msgs if not isinstance(m, SystemMessage)]
        ai_msg = remap_tool_calls(await llm_with_tools.ainvoke(msgs))
        if not getattr(ai_msg, "tool_calls", None) and not message_text(ai_msg):
            tool_bits = [
                str(m.content)[:4000]
                for m in msgs
                if isinstance(m, ToolMessage) and m.content
            ]
            packed = "\n\n".join(tool_bits)[:12000]
            ai_msg = await llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a project task manager. "
                            "Write a short, simple English summary for the user. "
                            "Do not call tools."
                        )
                    ),
                    HumanMessage(
                        content=(
                            "The user asked about Notion databases.\n\n"
                            f"Tool results:\n{packed or '(none)'}\n\n"
                            "Summarize what databases exist and what they contain."
                        )
                    ),
                ]
            )
        return {"messages": [ai_msg]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(notion_tools))
    graph.add_edge(START, "agent")

    def need_tool(state: MessagesState):
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph.add_conditional_edges("agent", need_tool, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=MemorySaver())


def message_text(message) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("text"):
                    parts.append(str(block.get("text")))
                elif block.get("type") == "text" and block.get("text"):
                    parts.append(str(block.get("text")))
        return "".join(parts).strip()
    return ""


def last_ai_text(messages) -> str:
    for m in reversed(messages):
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            text = message_text(m)
            if text:
                return text
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            text = message_text(m)
            if text:
                return text
    tool_bits = [
        str(m.content)[:1500]
        for m in messages
        if isinstance(m, ToolMessage) and m.content
    ]
    if tool_bits:
        return "Here is what Notion returned:\n\n" + "\n\n".join(tool_bits)[:4000]
    return "No response."



# import asyncio
# async def main():

#     graph = await build_graph()


# if __name__ == "__main__":
#     asyncio.run(main())
