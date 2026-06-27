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
* **Data Source:** NewsAPI.

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
| **Financial Data** | yfinance, NSE Open Data, BSE APIs | Quantitative market data ingestion |
| **News Retrieval** | NewsAPI | Financial news streaming |
| **Filing Parsing** | BeautifulSoup, PDF Parsing | Parsing SEC filings / corporate PDF reports |
| **Backend API** | FastAPI, SSE (`sse-starlette`), WebSockets | Real-time agent status streaming and price ticks |
| **Frontend** | React.js, HTML5 `EventSource`, WebSockets | Dynamic dashboard with streaming updates and live price feed |
| **Database** | PostgreSQL / MongoDB (Optional) | Persisting generated reports & cache |
| **Session Management** | LangChain Memory / ADK Sessions | Managing state across multi-turn agent sessions |

---

## Project Structure

```text
├── backend/
│   ├── app/
│   │   ├── agents/          # Agent implementations (coordinator, financial, news, filings, peer, writer)
│   │   ├── tools/           # Custom API tools (yfinance, newsapi, sec/filings scraper)
│   │   ├── services/        # Backend business logic and API route controllers
│   │   ├── main.py          # FastAPI main application file
│   │   └── config.py        # Configuration settings (API keys, LLM selections)
│   ├── requirements.txt     # Python dependencies
│   └── README.md            # Backend instructions
├── frontend/
│   ├── src/
│   │   ├── components/      # Reusable UI components (ReportViewer, StockChart)
│   │   ├── pages/           # React pages (Dashboard, Stocks)
│   │   ├── App.tsx          # Main React Application shell
│   │   └── index.css        # Tailwind or Custom CSS Styling
│   ├── package.json         # Node.js dependencies
│   └── README.md            # Frontend instructions
├── README.md                # Project landing page (this file)
└── implementation.md        # Technical design & implementation document
```

---

## Installation & Setup

Please refer to [implementation.md](file:///d:/Python/Project/Stock%20Analyst/implementation.md) for detailed configuration, API integration setup, and step-by-step installation instructions.

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

