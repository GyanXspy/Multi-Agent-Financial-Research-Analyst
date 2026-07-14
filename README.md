

https://github.com/user-attachments/assets/9d133837-acd7-4f5f-a0a2-944d146a6acc


# Multi-Agent Financial Research Analyst

An autonomous multi-agent system designed to collect, validate, analyze, and synthesize financial data to produce professional-grade investment research reports. Built using **LangChain**, the **Google Agent Development Kit (ADK)**, and **Gemini Family Models**.

## Table of Contents
1. [Business Context](#business-context)
2. [Workflow Architecture](#workflow-architecture)
3. [Specialized Agents](#specialized-agents)
4. [Technology Stack](#technology-stack)
5. [Project Structure](#project-structure)
6. [Installation & Setup](#installation--setup)
7. [Usage](#usage)
8. [Evaluation Criteria](#evaluation-criteria)
9. [Learning Outcomes](#learning-outcomes)

---

## Business Context

Equity research analysts spend significant time collecting, validating, and synthesizing financial information from multiple sources before preparing investment reports. This manual process involves retrieving historical financial data, tracking recent market developments, reviewing regulatory filings, comparing peer companies, and formulating investment recommendations.

This project automates this workflow by coordinating multiple specialized AI agents, each responsible for a specific research task. Built using **LangChain** and the **Google Agent Development Kit (ADK)**, the system leverages agent-based orchestration to gather data from financial APIs, news sources, and regulatory filings, ultimately producing a comprehensive investment research report.

---

## Workflow Architecture

The architecture demonstrates modern agentic AI concepts, including agent collaboration, tool integration, session management, and workflow orchestration.

```text
                    User Query (e.g., "Analyze AAPL")
                                │
                                ▼
                       Coordinator Agent
                                │
     ┌──────────────────┬───────┴──────────┬──────────────────┐
     ▼                  ▼                  ▼                  ▼
Financial Data        News              Filings        Peer Comparison
    Agent             Agent              Agent              Agent
 (yfinance/NSE/BSE)  (NewsAPI)    (BeautifulSoup/PDF)     (Valuation)
     │                  │                  │                  │
     └──────────────────┴───────┬──────────┴──────────────────┘
                                │
                                ▼
                       Thesis Writer Agent
                                │
                                ▼
                    Structured Investment Report
```

---

## Specialized Agents

The system consists of six specialized agents coordinated by a central orchestration agent:

### 1. Coordinator Agent
Serves as the primary entry point for user interactions.
* **Responsibilities:**
  * Interpret user queries and identify target company/stock symbol.
  * Delegate tasks to specialized agents (parallel or sequential execution).
  * Manage workflow execution & aggregate intermediate outputs.
  * Generate the final structured response.

### 2. Financial Data Agent
Retrieves quantitative financial information from market data providers.
* **Responsibilities:**
  * Fetch historical stock prices.
  * Retrieve income statements, balance sheets, and cash flow statements.
  * Calculate valuation metrics (P/E, EV/EBITDA, P/B, ROE, EBITDA Margin).
  * Retrieve operational metrics (Revenue, Net Income, EPS, Market Capitalization).
* **Data Sources:** Yahoo Finance (`yfinance`), BSE APIs, NSE Open Data.

### 3. News Agent
Monitors recent developments affecting the selected company.
* **Responsibilities:**
  * Retrieve recent news articles and filter financially material events.
  * Remove duplicate or irrelevant articles.
  * Summarize key developments (earnings, management changes, M&A, regulatory actions).
  * Identify potential positive and negative market catalysts.
* **Data Sources:** NewsAPI (primary), Google News RSS (automatic fallback when no API key is configured).

### 4. Filings Agent
Analyzes official corporate disclosures (annual reports, quarterly filings) to identify significant financial and operational changes.
* **Responsibilities:**
  * Download annual reports and quarterly filings.
  * Extract relevant sections (Management Discussion & Analysis (MD&A), Risk Factors, Financial Statements).
  * Identify year-over-year changes and emerging risks.
  * Summarize important disclosures.
* **Technologies:** BeautifulSoup, PDF/Text parsing libraries.

### 5. Peer Comparison Agent
Evaluates the company's performance relative to its competitors.
* **Responsibilities:**
  * Identify industry peers.
  * Retrieve comparable financial metrics.
  * Compute relative valuation ratios.
  * Generate comparison tables and rankings (Revenue Growth, P/E, ROE, Net Margin, Market Cap).
* **Output:** A comparative valuation table highlighting strengths and weaknesses relative to peers.

### 6. Thesis Writer Agent
Synthesizes outputs from all previous agents into a structured investment research report.
* **Responsibilities:**
  * Combine financial analysis, news summaries, filing insights, and peer comparisons.
  * Produce a concise executive summary.
  * Develop investment arguments (Bull Case, Bear Case) and key risks.
* **Final Report Structure:**
  1. Executive Summary
  2. Company Overview
  3. Financial Performance Analysis
  4. Recent News Highlights
  5. Regulatory Filing Insights
  6. Peer Comparison
  7. Bull Case
  8. Bear Case
  9. Key Risks
  10. Investment Conclusion

---

## Technology Stack

| Component | Technology | Description |
| :--- | :--- | :--- |
| **Multi-Agent Framework** | LangChain | For building LLM chains and agent workflows |
| **Agent Runtime** | Google ADK | For orchestrating agent sessions and tools |
| **Large Language Model** | Gemini Family Models | For reasoning, parsing, and report generation |
| **Financial Data** | yfinance | Quantitative market data ingestion (US, NSE `.NS`, BSE `.BO`, indices) |
| **News Retrieval** | NewsAPI + Google News RSS fallback | Financial news retrieval |
| **Filing Parsing** | BeautifulSoup, SEC EDGAR API | Parsing SEC 10-K/10-Q filings (cached CIK lookup) |
| **Backend API** | FastAPI, SSE (`sse-starlette`), WebSockets | Real-time agent status streaming and price ticks |
| **Auth & RBAC** | JWT (PyJWT) + bcrypt | Login, roles (`admin`/`analyst`), protected endpoints |
| **Rate Limiting** | slowapi | Per-IP limits on auth and research endpoints |
| **Frontend** | React 19, fetch-stream SSE, WebSockets | Authenticated dashboard with streaming updates and live price feed |
| **Database** | SQLite (SQLAlchemy async) | Users, roles, and persisted research reports |

---

## Project Structure

```text
├── backend/
│   ├── app/
│   │   ├── agents/          # Agent implementations (coordinator, financial, news, filings, peer, writer)
│   │   ├── routers/         # API routers (auth, research)
│   │   ├── main.py          # FastAPI app: middleware, WebSocket feed, entrypoint
│   │   ├── config.py        # Configuration settings (API keys, LLM selections)
│   │   ├── db.py            # Async SQLAlchemy engine + User/Report models
│   │   ├── security.py      # bcrypt hashing, JWT, auth dependencies
│   │   ├── rate_limit.py    # Shared slowapi limiter
│   │   └── schemas.py       # Pydantic request/response schemas
│   ├── tests/               # pytest suite (auth, RBAC, security)
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── components/      # PriceChart, PipelineStatus, ReportView, MetricCard, ErrorBoundary
│   │   ├── context/         # AuthContext (session state)
│   │   ├── lib/             # api client, fetch-based SSE reader, pipeline state
│   │   ├── pages/           # LoginPage, StockAnalystDashboard
│   │   ├── App.tsx          # Auth gate + error boundary
│   │   └── index.css        # Tailwind v4 design system
│   └── package.json         # Node.js dependencies
└── README.md                # Project landing page (this file)
```

---

## Installation & Setup

### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows (source venv/bin/activate on Unix)
pip install -r requirements.txt
copy .env.example .env         # then fill in the values below
python -m uvicorn app.main:app --reload
```

Required `.env` values:
| Variable | Purpose |
| :--- | :--- |
| `GEMINI_API_KEY` | Google Gemini API key (required) |
| `JWT_SECRET` | Token signing secret — generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `NEWS_API_KEY` | NewsAPI key (optional — falls back to Google News RSS) |

### Frontend
```bash
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

### First run
The **first account registered becomes the administrator**; all subsequent
accounts are analysts. Admins can manage roles from the dashboard's
User Management panel and can see every user's report history.

### Tests
```bash
cd backend
python -m pytest
```

---

## Evaluation Criteria

The system is evaluated against a curated benchmark of publicly traded companies with professional analyst reports:
1. **Structural Quality:** Logical organization, completeness, and readability of reports.
2. **Factual Accuracy:** Correct financial figures, accurate news summaries, and proper filings interpretation.
3. **Completeness:** Coverage of major financial metrics, material news, and peer comparisons.
4. **Investment Insight:** Strength of bull/bear cases, evidence-backed conclusions, and risk identification.

---

## Learning Outcomes

* Design and implement multi-agent AI systems using LangChain and Google ADK.
* Develop modular AI agents with specialized responsibilities.
* Integrate external tools and APIs into an agentic workflow.
* Manage persistent session state across multi-turn interactions.
* Implement real-time client-server communication using Server-Sent Events (SSE) and WebSockets.
* Retrieve, clean, and process structured and unstructured financial data.
* Generate comprehensive, publication-grade investment research reports using AI.

