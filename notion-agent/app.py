import asyncio
import threading
import uuid

import streamlit as st
from langchain_core.messages import HumanMessage

from agent_core import build_graph, last_ai_text

EXAMPLES = [
    ("Blocked work", "List all blocked tasks"),
    ("Amit's queue", "Show open tasks for Amit Kumar"),
    ("New task", "Create a task for Rahul Sharma: write API docs, due tomorrow, priority Medium"),
    ("Mark done", "Mark Priya Mehta dashboard charts as Done"),
]


@st.cache_resource
def get_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop


def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, get_loop())
    return future.result()


@st.cache_resource(show_spinner="Waking the Notion agent...")
def get_agent():
    return run_async(build_graph())


def friendly_error(err: Exception) -> str:
    text = str(err)
    if "Event loop is closed" in text:
        return (
            "The app hit an old async error. "
            "Stop Streamlit with Ctrl+C and run `streamlit run app.py` again."
        )
    if "API_KEY_INVALID" in text or "API key not valid" in text:
        return (
            "Gemini API key is not valid. "
            "Get a new key from https://aistudio.google.com/apikey "
            "then put it in .env as GEMINI_API_KEY and restart the app."
        )
    return f"Something went wrong: {text[:300]}"


def ask_agent(message: str, thread_id: str) -> str:
    agent = get_agent()
    result = run_async(
        agent.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config={"configurable": {"thread_id": thread_id}},
        )
    )
    return last_ai_text(result["messages"])


def inject_css():
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Syne:wght@700;800&display=swap');

html, body, [class*="css"]  {
  font-family: "DM Sans", sans-serif;
}
.stApp {
  background:
    radial-gradient(1200px 500px at 10% -10%, rgba(94, 234, 212, 0.16), transparent 50%),
    radial-gradient(900px 400px at 100% 0%, rgba(99, 102, 241, 0.18), transparent 45%),
    #070B14;
}
#MainMenu, footer, header {visibility: hidden;}
.block-container {padding-top: 1.2rem; padding-bottom: 6rem; max-width: 1100px;}

.hero {
  border: 1px solid rgba(94, 234, 212, 0.18);
  background: linear-gradient(180deg, rgba(18, 26, 42, 0.92), rgba(12, 18, 32, 0.75));
  border-radius: 24px;
  padding: 28px 32px 22px;
  box-shadow: 0 24px 80px rgba(0,0,0,0.35);
  margin-bottom: 18px;
}
.kicker {
  color: #5EEAD4;
  letter-spacing: 0.16em;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
}
.hero h1 {
  font-family: Syne, sans-serif;
  font-size: 2.35rem;
  margin: 8px 0 6px;
  color: #F8FBFF;
}
.hero p {color: #9FB0C9; margin: 0; font-size: 1.02rem;}
.pills {display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px;}
.pill {
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.04);
  color: #D5E2F2;
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 0.78rem;
}

.stat {
  border: 1px solid rgba(255,255,255,0.07);
  background: rgba(18, 26, 42, 0.8);
  border-radius: 18px;
  padding: 14px 16px;
}
.stat b {display:block; color:#F8FBFF; font-size:1.05rem;}
.stat span {color:#8EA0B8; font-size:0.8rem;}

.stChatMessage {
  background: rgba(18, 26, 42, 0.72) !important;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 18px;
  padding: 8px 6px;
}
div[data-testid="stChatMessage"]:has(div[aria-label="Chat message from user"]) {
  border-color: rgba(94, 234, 212, 0.22);
}
.stButton>button {
  border-radius: 12px;
  border: 1px solid rgba(94, 234, 212, 0.25);
  background: rgba(94, 234, 212, 0.08);
  color: #E8EEF8;
}
.stButton>button:hover {
  border-color: #5EEAD4;
  background: rgba(94, 234, 212, 0.16);
}
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0B1220, #0A101C);
  border-right: 1px solid rgba(255,255,255,0.06);
}
.empty {
  text-align: center;
  padding: 36px 16px 12px;
  color: #9FB0C9;
}
.empty h3 {color: #F8FBFF; font-family: Syne, sans-serif; margin-bottom: 6px;}
</style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(
    page_title="NovaTech Task Agent",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "pending" not in st.session_state:
    st.session_state.pending = None

with st.sidebar:
    st.markdown("### ✦ NovaTech")
    st.caption("AI task desk for the client workspace")
    st.markdown("---")
    if st.button("New conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.pending = None
        st.rerun()
    st.markdown("#### Quick actions")
    for label, text in EXAMPLES:
        if st.button(label, use_container_width=True, key=f"ex-{label}"):
            st.session_state.pending = text
            st.rerun()
    st.markdown("---")
    st.caption("Employees + Tasks live in Notion.\nGemini talks. MCP writes.")

left, right = st.columns([1.45, 0.55])
with left:
    st.markdown(
        """
<div class="hero">
  <div class="kicker">Client operations · Notion native</div>
  <h1>Task Agent</h1>
  <p>Create, update, and track employee work in Notion.</p>
  <div class="pills">
    <span class="pill">NovaTech-Team</span>
    <span class="pill">NovaTech-Tasks</span>
    <span class="pill">Blocked · Doing · Done</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )
with right:
    st.markdown(
        """
<div class="stat"><b>6 people</b><span>Active client team</span></div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="stat"><b>15 sample tasks</b><span>Ready for demo queries</span></div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="stat"><b>Live Notion</b><span>Reads and writes the real DB</span></div>
        """,
        unsafe_allow_html=True,
    )

if not st.session_state.messages and not st.session_state.pending:
    st.markdown(
        """
<div class="empty">
  <h3>Start with a real ops question</h3>
  <p>Ask about blocked work, one employee, or create a task in one line.</p>
</div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    for col, (label, text) in zip(cols, EXAMPLES):
        with col:
            if st.button(text, use_container_width=True, key=f"main-{label}"):
                st.session_state.pending = text
                st.rerun()

for item in st.session_state.messages:
    with st.chat_message(item["role"]):
        st.markdown(item["content"])

typed = st.chat_input("Ask anything about NovaTech tasks…")
if typed:
    st.session_state.pending = typed

if st.session_state.pending:
    prompt = st.session_state.pending
    st.session_state.pending = None
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Talking to Notion..."):
            try:
                answer = ask_agent(prompt, st.session_state.thread_id)
            except Exception as err:
                answer = friendly_error(err)
        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
