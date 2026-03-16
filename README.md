<div align="center">

<h1>🧠 SimpleContext</h1>

<p><strong>Universal AI Brain for AI Agents</strong><br/>
Tiered Memory · Context Scoring · Intent Planning · Zero Dependencies</p>

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-135%20passing-brightgreen?style=flat-square)](tests/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero-success?style=flat-square)](setup.py)
[![Version](https://img.shields.io/badge/Version-4.1-blueviolet?style=flat-square)](CHANGELOG.md)

<br/>

> **SimpleContext is not another vector database wrapper.**
> It's a structured context brain — tiered memory, intent-aware retrieval,
> fact extraction, and importance scoring. Without a single external dependency.

<br/>

[Quick Start](#-quick-start) · [Architecture](#️-architecture) · [Agent System](#-agent-system) · [API Reference](#-api-reference) · [Comparison](#-comparison)

</div>

---

## 🤔 Why SimpleContext?

Most AI agent frameworks treat memory as a flat list of messages. This breaks down fast:

```
❌ Flat memory:    [msg1, msg2, ... msg500]  → retrieval gets noisy
✅ Tiered memory:  working · episodic · semantic  → structured, scored, evolved
```

SimpleContext gives your agent a **structured brain** — not just a chat log.

---

## ✨ Features

| | Feature | Description |
|---|---|---|
| 🧠 | **3-Tier Memory** | `working` (active) · `episodic` (sessions) · `semantic` (long-term facts) |
| 🎯 | **Intent Planning** | Auto-detect intent → smart retrieval strategy per query type |
| 📊 | **Context Scoring** | `relevance×0.55 + importance×0.25 + recency×0.10 + path_priority×0.10` |
| 🔍 | **Fact Extraction** | Rule-based: `"user uses Proxmox"`, `"user project Mangafork"` |
| ♻️ | **Memory Evolution** | Jaccard dedup · conflict resolution · importance decay |
| ⚡ | **LRU Cache** | 30s TTL cache for repeated queries — reduces DB load |
| 🤖 | **Agent YAML** | Define agents in YAML · hot-reload without restart |
| 🔗 | **Agent Chaining** | Agent A handoff to Agent B based on user message |
| 💾 | **Multi-Storage** | SQLite (default, zero install) · Redis · PostgreSQL |
| 🔌 | **Plugin System** | Hooks + persistent state + dependency resolver |
| 🔄 | **Backward Compat** | All v3 API still works — zero breaking changes |
| 📦 | **Zero Dependencies** | Only Python built-ins: `sqlite3`, `json`, `re`, `datetime` |

---

## 🏗️ Architecture

```
User Message
      │
      ▼
 AgentRouter ──────── agents/*.yaml  (hot-reload, TF-IDF routing)
      │
      ▼
 ContextPlanner
      │  intent : coding | personal | task | knowledge | conversation
      │  budget : { working:5, episodic:2, semantic:4, skills:3 }
      ▼
 ContextEngine
      ├── Retriever   → collect candidates
      ├── Resolver    → TTL check, mark expired
      ├── Filter      → active nodes only
      ├── Scorer      → rank by relevance + importance + recency + path
      └── Selector    → enforce budget + max_nodes + max_chars
      │
      ▼
 PromptBuilder  (deterministic, bullet-format per tier)
      │
      ▼
    LLM  ←→  Gemini / OpenAI / Claude / Ollama / any
      │
      ▼
 MemoryProcessor
      ├── store messages  → working tier
      ├── extract facts   → semantic tier (rule-based, no LLM)
      ├── dedup           → Jaccard similarity ≥ 0.65
      ├── conflict resolve → confidence-based supersedes
      └── update importance scores
```

---

## 🚀 Quick Start

**No install needed.** Copy `simplecontext/` folder into your project.

```python
from simplecontext import SimpleContext

sc = SimpleContext("config.yaml")

# Simple mode (v3 API — backward compatible)
result   = sc.router.route(user_id, message)
messages = sc.prepare_messages(user_id, message, result)
reply    = your_llm(messages)
reply    = sc.process_response(user_id, message, reply, result)

# Full mode (v4 API — one liner)
ctx   = sc.chat(user_id, message)
reply = your_llm(ctx.messages)
reply = ctx.save(reply)
```

### Works with any LLM

```python
# Gemini
import litellm
reply = litellm.completion(model="gemini/gemini-2.0-flash",
    messages=ctx.messages).choices[0].message.content

# OpenAI
from openai import OpenAI
reply = OpenAI().chat.completions.create(
    model="gpt-4o", messages=ctx.messages).choices[0].message.content

# Ollama (local)
import ollama
reply = ollama.chat(model="llama3", messages=ctx.messages)["message"]["content"]

# Anthropic Claude
import anthropic
sys_msg = next(m["content"] for m in ctx.messages if m["role"] == "system")
history = [m for m in ctx.messages if m["role"] != "system"]
reply = anthropic.Anthropic().messages.create(
    model="claude-3-5-sonnet-20241022",
    system=sys_msg, messages=history, max_tokens=1024).content[0].text
```

---

## 🤖 Agent System

Define agents in YAML. **Bot doesn't need to restart** when you edit or add agents.

```yaml
# agents/coding.yaml
name: coding
description: Expert programmer for all languages

triggers:
  keywords: [code, bug, error, python, javascript, debug, fix]
  priority: 10

personality:
  default: |
    You are a senior software engineer.
    Always use proper code blocks with language tags.
  beginner: |
    You are a patient programming teacher.
    Explain every step with simple examples.
  expert: |
    Principal engineer. Be concise and technical.

skills:
  - name: code_format
    content: Always use ```language for all code.
    priority: 10

chain:
  - condition: deploy OR server OR docker
    to: devops
    message: Routing to DevOps agent.
```

**Add a new agent** = create a new `.yaml` file in `agents/`. Done.

---

## 📖 API Reference

### Memory (v3 API)

```python
mem = sc.memory(user_id)

mem.add_user("hello!")
mem.add_assistant("hi there!")
history = mem.get_for_llm(limit=10)   # ready for LLM

# Persistent user facts
mem.remember("name", "Alice")
mem.remember("stack", "Python + FastAPI")
mem.recall("name")                    # → "Alice"

# Compress old messages into episodic summary
mem.compress(keep_last=10)
```

### TieredMemory (v4 API)

```python
ctx = sc.context(user_id)

ctx.working.add("debug this error", NodeKind.MESSAGE)
ctx.episodic.add("session summary", NodeKind.SUMMARY)
ctx.semantic.add("user uses Proxmox", NodeKind.FACT, importance=0.8)

ctx.stats()   # → {"working": 5, "episodic": 1, "semantic": 3}
ctx.prune()   # remove expired + deleted nodes from DB
```

### Intent → Retrieval Strategy

| Intent | Working | Episodic | Semantic | Skills |
|---|:---:|:---:|:---:|:---:|
| `conversation` | ✅ | ✅ | ❌ | ❌ |
| `personal` | ✅ | ❌ | ✅ | ❌ |
| `coding` | ✅ | ✅ | ✅ | ✅ |
| `knowledge` | ❌ | ❌ | ✅ | ❌ |
| `task` | ✅ | ✅ | ✅ | ✅ |

### Debug & Utilities

```python
sc.enable_debug(True)         # log retrieval pipeline details
sc.apply_decay(user_id)       # apply importance decay (call periodically)
sc.apply_decay()              # apply to all users

stats = sc.engine.get_stats(plan)
# → {"candidates": 37, "active": 28, "selected": 11, "total_chars": 3200}
```

---

## ⚙️ Configuration

```yaml
# config.yaml
storage:
  backend: sqlite          # sqlite | memory | redis | postgresql
  path: ./sc_data.db

memory:
  default_limit: 20
  ttl_hours:
    working: 2             # working nodes expire after 2 hours
    episodic: 720          # episodic nodes expire after 30 days
  compression:
    enabled: false
    threshold: 50
    keep_last: 10

agents:
  folder: ./agents
  hot_reload: true
  default: general

plugins:
  enabled: true
  folder: ./plugins

debug:
  retrieval: false
```

---

## 🔌 Plugin System

```python
from simplecontext.plugins.base import BasePlugin

class MyPlugin(BasePlugin):
    name       = "my_plugin"
    depends_on = []            # declare dependencies

    def setup(self):
        self.count = self.state.get("count", 0)  # persistent state

    # Hooks available:
    def on_message_saved(self, user_id, role, content, tags, metadata): ...
    def on_before_llm(self, user_id, agent_id, messages) -> list: ...
    def on_after_llm(self, user_id, agent_id, response) -> str: ...
    def on_agent_routed(self, user_id, agent_id, message): ...
    def on_prompt_build(self, agent_id, prompt) -> str: ...
    def on_export(self, data) -> dict: ...

sc.use(MyPlugin())
# or drop the file in ./plugins/ — auto-loaded on startup
```

---

## 📁 Project Structure

```
SimpleContext/
├── simplecontext/
│   ├── core.py              ← SimpleContext + ChatContext (entry point)
│   ├── memory.py            ← Memory (v3) + TieredMemory (v4)
│   ├── skills.py            ← Skills: groups, conditions, inheritance
│   ├── enums.py             ← Tier, NodeKind, NodeStatus, Intent
│   ├── context/
│   │   ├── node.py          ← ContextNode + validator
│   │   ├── planner.py       ← ContextPlanner + RetrievalPlan
│   │   ├── engine.py        ← ContextEngine facade + LRU cache
│   │   ├── retriever.py     ← collect candidates
│   │   ├── resolver.py      ← TTL → mark expired
│   │   ├── scorer.py        ← scoring formula
│   │   ├── selector.py      ← budget enforcement
│   │   ├── builder.py       ← PromptBuilder
│   │   ├── processor.py     ← MemoryProcessor + decay
│   │   └── cache.py         ← LRU cache
│   ├── storage/
│   │   ├── sqlite.py        ← default, zero install
│   │   ├── redis.py         ← pip install redis
│   │   └── postgres.py      ← pip install psycopg2-binary
│   ├── agent/
│   │   ├── schema.py        ← parse YAML agent definitions
│   │   ├── registry.py      ← hot-reload agent files
│   │   └── router.py        ← TF-IDF routing + chaining
│   └── plugins/
│       ├── base.py          ← BasePlugin + hooks
│       ├── loader.py        ← dynamic loader + dependency resolver
│       └── state.py         ← persistent plugin state
├── agents/                  ← agent YAML definitions
├── plugins/                 ← drop custom plugins here
├── tests/
│   ├── test_all.py          ← 107 unit tests
│   └── test_benchmark.py    ← 28 accuracy + benchmark tests
└── config.yaml.example
```

---

## 📊 Comparison

| | **SimpleContext** | OpenViking | LangChain | AutoGPT |
|---|:---:|:---:|:---:|:---:|
| **Setup time** | < 1 min | 30+ min | ~5 min | ~10 min |
| **Dependencies** | **Zero** | Go + VLM | Many | Many |
| **Tiered Memory** | ✅ | ❌ | ❌ | ❌ |
| **Intent Planning** | ✅ | ❌ | ❌ | ❌ |
| **Context Scoring** | ✅ | ❌ | ❌ | ❌ |
| **Fact Extraction** | ✅ | ❌ | ❌ | ❌ |
| **Conflict Handling** | ✅ | ❌ | ❌ | ❌ |
| **Agent YAML + Hot-reload** | ✅ | ❌ | ❌ | ❌ |
| **Agent Chaining** | ✅ | ❌ | ⚠️ | ⚠️ |
| **Plugin System** | ✅ | ❌ | ⚠️ | ❌ |
| **Multi-Storage** | ✅ | VectorDB | VectorDB | VectorDB |
| **Semantic Search** | ❌ keyword | ✅ vector | ✅ vector | ✅ vector |

---

## 🧪 Tests

```bash
python -m unittest discover tests -v
# Ran 135 tests in 1.2s — OK
```

---

## 📄 License

MIT — free to use, modify, and distribute.

---

<div align="center">

Built with ❤️ — zero dependencies, maximum brain.

**[⭐ Star this repo](https://github.com/zacxyonly/SimpleContext)** if you find it useful!

</div>
