# 🧠 SimpleContext v4

> **Universal AI Brain** — Tiered Memory, Context Planning, Smart Retrieval.
> Zero external dependencies. Fully backward compatible.

---

## ✨ Apa yang Baru di v4

| Fitur | v3 | v4 |
|---|---|---|
| Memory | Flat list | **3 Tier** (working/episodic/semantic) |
| Retrieval | N pesan terakhir | **Score-based** (relevance+importance+recency) |
| Context planning | Auto-route keyword | **ContextPlanner** → RetrievalPlan |
| Memory evolution | Compress potong | **MemoryProcessor** extract facts + dedup |
| Conflict handling | ❌ | **Supersedes** + confidence scoring |
| Dedup | ❌ | **Jaccard similarity** untuk facts |
| Node metadata | ❌ | **ContextNode** (path, tier, kind, status, importance...) |
| Budget control | ❌ | **Per-tier + global** (max_nodes, max_chars) |
| API v3 | ✅ | **Tetap jalan**, tidak ada breaking change |

---

## 🏗️ Arsitektur

```
SimpleContext v4
│
├── context/
│   ├── ContextNode        ← unit terkecil: path + tier + kind + score
│   ├── ContextPlanner     ← query → RetrievalPlan (intent, budget, flags)
│   ├── ContextEngine      ← facade: collect→resolve→filter→score→select
│   │   ├── ContextRetriever   ← ambil candidates dari storage
│   │   ├── StatusResolver     ← TTL check → mark expired
│   │   ├── CandidateFilter    ← filter status=active
│   │   ├── ContextScorer      ← rank: relevance*0.6 + importance*0.3 + recency*0.1
│   │   └── ContextSelector    ← enforce budget + global limits
│   ├── PromptBuilder      ← nodes → messages list (deterministic)
│   └── MemoryProcessor    ← turn → extract facts → dedup → conflict → store
│
├── memory/
│   ├── TieredMemory       ← working | episodic | semantic
│   └── Memory             ← v3 compat facade (blended working+episodic)
│
├── storage/
│   ├── SQLite (default)
│   ├── Redis (opsional)
│   └── PostgreSQL (opsional)
│
└── agent/
    ├── AgentRegistry      ← hot-reload YAML agents
    └── AgentRouter        ← TF-IDF routing + chaining
```

---

## 🚀 Quick Start

```python
from simplecontext import SimpleContext

sc = SimpleContext("config.yaml")
```

### Mode v3 (backward compat — tidak ada yang perlu diubah)

```python
result   = sc.router.route(user_id, message)
messages = sc.prepare_messages(user_id, message, result)
reply    = your_llm(messages)
reply    = sc.process_response(user_id, message, reply, result)
```

### Mode v4 (full context engine)

```python
# High-level: satu method untuk segalanya
ctx   = sc.chat(user_id, message)
reply = your_llm(ctx.messages)
reply = ctx.save(reply)

# Low-level: kontrol penuh
profile = sc.memory(user_id).get_profile()
plan    = sc.planner.plan(message, user_id, profile=profile, agent_id="coding")
nodes   = sc.engine.retrieve(plan)
msgs    = sc.builder.build(system_prompt, nodes, message)
reply   = your_llm(msgs)

from simplecontext import ProcessTurn
turn = ProcessTurn(user_id, message, reply, agent_id="coding", used_nodes=nodes)
sc.processor.process(turn)
```

---

## 📖 ContextNode

Unit terkecil dari context system.

```python
from simplecontext import ContextNode, Tier, NodeKind, NodeStatus

node = ContextNode(
    user_id    = "user_123",
    path       = "/memory/semantic/user_123/abc",
    tier       = Tier.SEMANTIC,
    kind       = NodeKind.FACT,
    content    = "user pakai python untuk data science",
    importance = 0.7,
    confidence = 0.9,
    source     = "user",
    tags       = ["python", "data-science"],
)
```

### Tiers

| Tier | Kapan Dipakai | Default TTL |
|---|---|---|
| `working` | Pesan aktif, task state | 2 jam |
| `episodic` | Ringkasan sesi, interaction history | 30 hari |
| `semantic` | Facts, knowledge jangka panjang | Permanen |

### Kinds per Tier

| Tier | Kind yang Valid |
|---|---|
| `working` | `message`, `fact`, `task_state` |
| `episodic` | `summary`, `fact` |
| `semantic` | `fact`, `resource` |
| Skills namespace | `skill` (path `/skills/...`) |

### Node Status

```
active → normal, bisa di-retrieve
expired → TTL habis, soft deleted
superseded → digantikan fact baru
deleted → dihapus manual
```

---

## 📖 TieredMemory (v4 API)

```python
ctx = sc.context(user_id)

# Working tier — pesan aktif
ctx.working.add("isi pesan", NodeKind.MESSAGE, importance=0.8)
ctx.working.get(limit=10)
ctx.working.count()

# Episodic tier — ringkasan sesi
ctx.episodic.add("ringkasan sesi tadi", NodeKind.SUMMARY)
ctx.episodic.get()

# Semantic tier — knowledge jangka panjang
ctx.semantic.add("user pakai docker", NodeKind.FACT, confidence=0.9)
ctx.semantic.get()

# Stats
ctx.stats()  # → {"working": 5, "episodic": 1, "semantic": 3}

# Prune: hapus expired + deleted dari DB
ctx.prune()
```

---

## 📖 ContextPlanner + ContextEngine

```python
# Plan: tentukan strategi retrieval
plan = sc.planner.plan(
    query    = "ada bug di python saya",
    user_id  = user_id,
    profile  = sc.memory(user_id).get_profile(),
    agent_id = "coding",
)
# plan.intent = "coding"
# plan.working = True, plan.semantic = True
# plan.include_skills = True (ada agent_id + coding intent)
# plan.budget = {"working": 6, "episodic": 2, "semantic": 4, "skills": 3}

# Retrieve: pipeline lengkap
nodes = sc.engine.retrieve(plan)
# → list ContextNode sudah di-score dan di-select

# Debug info
info = sc.engine.get_stats(plan)
# → {"candidates": 20, "active": 15, "selected": 10, "total_chars": 3200}
```

### Intent Detection (rule-based, zero dependency)

| Intent | Keyword Signals |
|---|---|
| `coding` | code, bug, error, python, javascript, debug... |
| `personal` | saya, aku, prefer, suka, i use, i like... |
| `task` | tolong, buatkan, generate, tugas, step... |
| `knowledge` | apa, what, explain, jelaskan, mengapa... |
| `conversation` | (default kalau tidak ada signal) |

### Scoring Formula

```
score = relevance * 0.6 + importance * 0.3 + recency * 0.1

relevance = text_overlap * 0.6 + tag_overlap * 0.25 + path_overlap * 0.15
recency   = 2^(-age_hours / half_life)  # exponential decay
```

---

## 📖 MemoryProcessor

```python
from simplecontext import ProcessTurn

turn = ProcessTurn(
    user_id            = user_id,
    user_message       = "saya menggunakan docker untuk deployment",
    assistant_response = "Docker bagus untuk containerization.",
    agent_id           = "devops",
    used_nodes         = nodes,          # untuk update importance
    runtime_state      = {"intent": "task"},
)

stored_nodes = sc.processor.process(turn)
```

Pipeline internal:
1. Simpan pesan user + assistant → `working` tier
2. Extract facts dari pesan user (heuristik, tanpa LLM)
3. Dedup via Jaccard (hanya `fact` kind, max 20 token)
4. Conflict resolution (similarity ≥ 0.65 + confidence check)
5. Assign ke `semantic` tier
6. Update importance node yang dipakai (`+0.02` per use)

### Importance Delta

| Event | Delta |
|---|---|
| Node dipakai dalam retrieval | `+0.02` |
| Fact baru dari user | `+0.10` |
| Node di-supersede | `-0.10` |
| Daily decay | `-0.005` |

---

## 📖 PromptBuilder

```python
messages = sc.builder.build(
    system_base  = "Kamu adalah AI expert.",
    nodes        = retrieved_nodes,
    user_message = message,
    history      = sc.memory(user_id).get_for_llm(limit=5),
    profile      = sc.memory(user_id).get_profile(),
)
```

Output format (deterministic):
```
[System]
Kamu adalah AI expert.

USER PROFILE:
- nama: Budi
- level: expert

[WORKING CONTEXT]
User: pesan terbaru...

[EPISODIC MEMORY]
Ringkasan sesi sebelumnya...

[SEMANTIC KNOWLEDGE]
user pakai python untuk data science

[RELEVANT SKILLS]
Skill [code_format]: Gunakan code block...
```

---

## ⚙️ Config (`config.yaml`)

```yaml
storage:
  backend: sqlite        # sqlite | memory | redis | postgresql
  path: ./sc_data.db

memory:
  default_limit: 20
  ttl_hours:
    working: 2
    episodic: 720        # 30 hari
    # semantic: null     # permanen (default)
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

export:
  folder: ./exports
```

---

## 🔌 Kompatibel Semua LLM

```python
# Gemini via LiteLLM
import litellm
ctx      = sc.chat(user_id, message)
reply    = litellm.completion(model="gemini/gemini-2.0-flash",
               api_key=KEY, messages=ctx.messages).choices[0].message.content
ctx.save(reply)

# OpenAI
from openai import OpenAI
reply = OpenAI().chat.completions.create(
    model="gpt-4o", messages=ctx.messages).choices[0].message.content
ctx.save(reply)

# Anthropic Claude
import anthropic
sys = next(m["content"] for m in ctx.messages if m["role"]=="system")
hist = [m for m in ctx.messages if m["role"] != "system"]
reply = anthropic.Anthropic().messages.create(
    model="claude-3-5-sonnet-20241022", system=sys,
    messages=hist, max_tokens=1024).content[0].text
ctx.save(reply)

# Ollama (lokal)
import ollama
reply = ollama.chat(model="llama3", messages=ctx.messages)["message"]["content"]
ctx.save(reply)
```

---

## 🧪 Tests

```bash
python -m unittest discover tests -v
# 107 tests, ~0.1 detik
```

---

## 📊 Perbandingan

| | SimpleContext v4 | OpenViking | LangChain | AutoGPT |
|---|---|---|---|---|
| **Setup** | Copy folder | 30+ menit | pip install | pip install |
| **Dependencies** | Zero | Go + VLM | Banyak | Banyak |
| **Tiered Memory** | ✅ | ❌ | ❌ | ❌ |
| **Context Scoring** | ✅ | ❌ | ❌ | ❌ |
| **Conflict handling** | ✅ | ❌ | ❌ | ❌ |
| **Memory dedup** | ✅ | ❌ | ❌ | ❌ |
| **Budget control** | ✅ | ❌ | ❌ | ❌ |
| **Agent YAML** | ✅ | ❌ | ❌ | ❌ |
| **Hot-reload** | ✅ | ❌ | ❌ | ❌ |
| **Semantic search** | ❌ keyword | ✅ vector | ✅ vector | ✅ vector |
| **Backward compat** | ✅ v3 API | N/A | N/A | N/A |

---

## 📄 Lisensi

MIT License
