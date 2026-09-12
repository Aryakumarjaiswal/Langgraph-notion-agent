# 🤖 Notion AI Task Agent

An enterprise-ready, cloud-native AI task management system that enables users to interact with Notion workspace databases using natural language commands. Powered by **Google Gemini** and **LangGraph**, the agent dynamically plans, executes, and updates tasks via the **Notion Model Context Protocol (MCP)**.

The application features a **Streamlit** chat interface, a **FastAPI** backend with JWT authentication, and is engineered for production with **Docker**, **Kubernetes (HPA)**, and **GitHub Actions CI/CD**.

---

## 🏗️ System Architecture

```text
                             ┌──────────────────────────────────────────────┐
                             │           Kubernetes Cluster (EKS)           │
                             │                                              │
┌──────────────┐   HTTP/WS   │  ┌──────────────┐     ┌───────────────────┐  │
│ User Browser │ ──────────> │  │ K8s Service  │ ──> │   Streamlit Pods  │  │
└──────────────┘             │  └──────────────┘     │  (Autoscaled HPA) │  │
                             └───────────────────────┴─────────┬─────────┘──┘
                                                               │
                                                     LangGraph ReAct Loop
                                                               │
                                             ┌─────────────────┴─────────────────┐
                                             ▼                                   ▼
                                  ┌────────────────────┐              ┌─────────────────────┐
                                  │   Google Gemini    │              │     Notion MCP      │
                                  │  (LLM Reasoning)   │              │   (Database I/O)    │
                                  └────────────────────┘              └─────────────────────┘

```

---

## 🛠️ Tech Stack

- 🧠 **Agent Orchestration:** LangGraph (ReAct pattern with conditional tool routing)
- ⚡ **LLM Engine:** Google Gemini (`gemini-3.6-flash`)
- 🔌 **Tool Integration:** Notion MCP 
- 🖥️ **User Interface:** Streamlit 
- 🚀 **Backend API:** FastAPI with JWT Authentication
- 🐳 **Containerization & Orchestration:** Docker, Kubernetes (Deployment, ClusterIP Service, HPA)
- 🔄 **CI/CD:** GitHub Actions (Automated image build & registry push)

---

## 🌟 Key Engineering Highlights

- 🔄 **ReAct Flow Control:** Implements dynamic conditional edges in LangGraph to inspect agent message outputs and automatically loop between tool execution and terminal responses.
- 📈 **Auto-Scaling Infrastructure:** Configured with Kubernetes **Horizontal Pod Autoscaler (HPA)** to dynamically scale pod replicas (2–6 pods) based on target CPU utilization (70%).
- ⚙️ **CI/CD Pipeline:** Automated GitHub Actions workflow triggers on push to `main` to build, tag, and push Docker images.
- 🌐 **Stateless Multi-Pod Readiness:** Managed session execution enabling seamless horizontal scaling without shared state bottlenecks.

---

## 📂 Repository Structure

```text
NOTION-MCP/
├── .github/
│   └── workflows/
│       └── cicd.yml           # GitHub Actions CI/CD pipeline
├── k8s/
│   ├── deployment.yaml        # K8s Deployment manifest & resource limits
│   ├── hpa.yaml               # Horizontal Pod Autoscaler (CPU target: 70%)
│   └── service.yaml           # ClusterIP Service configuration
├── notion-agent/
│   ├── .streamlit/            # UI theme configuration
│   ├── .env.example           # Environment template
│   ├── agent_core.py          # LangGraph state machine & system prompts
│   ├── apis.py                # FastAPI endpoints + JWT auth logic
│   ├── app.py                 # Streamlit async chat UI
│   ├── Dockerfile             # Multi-stage container build definition
│   ├── gemini_chat.py         # Direct Gemini LLM handler
│   └── requirements.txt       # Python dependencies
├── .env                       # Local environment secrets (gitignored)
└── README.md

```

---

## ⚙️ Environment Setup

Create a `.env` file inside the root directory based on `.env.example`:

```bash
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3.6-flash
NOTION_MCP_TOKEN=ntn_your-notion-integration-token
NOTION_VERSION=2022-06-28
NOTION_PARENT_PAGE_ID=your-notion-page-id
EMPLOYEES_DATABASE_ID=your-employees-db-id
TASKS_DATABASE_ID=your-tasks-db-id
JWT_SECRET=your-secure-jwt-secret

```

---

## 💻 Local Development

1. 📥 **Clone the repository:**

```bash
git clone https://github.com/your-username/NOTION-MCP.git
cd NOTION-MCP/notion-agent

```

1. 🐍 **Set up Python Virtual Environment:**

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

```

1. 🎈 **Run the Streamlit Chat App:**

```bash
streamlit run app.py

```

1. ⚡ **Run the FastAPI Backend (Optional):**

```bash
uvicorn apis:app --reload --port 8000

```

---

## 🚢 Docker & Kubernetes Deployment

### 🐳 Run via Docker

```bash
docker build -t notion-agent:latest ./notion-agent
docker run -p 8501:8501 --env-file .env notion-agent:latest

```

### ☸️ Deploy to Kubernetes

```bash
# Create cluster secret from .env
kubectl create secret generic notion-agent-secrets --from-env-file=.env

# Apply Kubernetes manifests
kubectl apply -f k8s/

# Verify resources
kubectl get pods,svc,hpa

```

---

## 💬 Example Agent Queries

- 🔍 *"List all blocked tasks in the workspace."*
- 📝 *"Create a task for Rahul Sharma: Write API documentation, due tomorrow, priority High."*
- 📋 *"Show all open tasks assigned to Amit Kumar."*
- ✅ *"Mark the dashboard charts task as Done."*
