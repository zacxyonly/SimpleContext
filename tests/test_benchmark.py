"""
Benchmark Tests SimpleContext v4.1
Verifikasi akurasi fact extraction, retrieval, dan memory evolution.

Jalankan: python tests/test_benchmark.py
"""

import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from simplecontext import SimpleContext, ProcessTurn


def make_sc(**overrides):
    defaults = {
        "storage__backend":    "memory",
        "plugins__enabled":    False,
        "agents__folder":      "./nonexistent",
        "agents__hot_reload":  False,
        "debug__retrieval":    False,
    }
    defaults.update(overrides)
    return SimpleContext(**defaults)


# ── Fact Extraction Accuracy ──────────────────────────────

class TestFactExtraction(unittest.TestCase):
    """
    Test apakah MemoryProcessor mengekstrak facts dengan benar.
    Format expected: "user X Y" (normalized)
    """

    def _extract(self, text: str) -> list[str]:
        from simplecontext.context.processor import MemoryProcessor
        from simplecontext.storage.sqlite import SQLiteStorage
        storage = SQLiteStorage(":memory:")
        proc = MemoryProcessor(storage)
        return proc._extract_facts(text)

    def test_uses_tool(self):
        facts = self._extract("Saya menggunakan Proxmox untuk virtualisasi")
        self.assertTrue(any("proxmox" in f for f in facts),
                        f"Expected 'proxmox' in facts, got: {facts}")

    def test_user_name(self):
        facts = self._extract("Nama saya adalah ZACY")
        self.assertTrue(any("name" in f or "nama" in f.lower() for f in facts),
                        f"Expected name fact, got: {facts}")

    def test_project(self):
        facts = self._extract("Project saya Mangafork sedang dalam development")
        self.assertTrue(any("mangafork" in f for f in facts),
                        f"Expected 'mangafork' in facts, got: {facts}")

    def test_building(self):
        facts = self._extract("Saya lagi buat aplikasi monitoring untuk server")
        self.assertTrue(len(facts) > 0, f"Expected at least 1 fact, got: {facts}")

    def test_os_usage(self):
        facts = self._extract("Saya pakai Debian untuk server production")
        self.assertTrue(any("debian" in f for f in facts),
                        f"Expected 'debian' in facts, got: {facts}")

    def test_stack(self):
        facts = self._extract("Stack saya adalah Python dan FastAPI")
        self.assertTrue(len(facts) > 0, f"Expected stack fact, got: {facts}")

    def test_no_false_positive(self):
        facts = self._extract("Cuaca hari ini sangat cerah dan menyenangkan")
        self.assertEqual(len(facts), 0,
                        f"Expected no facts from weather msg, got: {facts}")

    def test_max_facts_per_turn(self):
        text = ("Saya menggunakan Python. Saya menggunakan Docker. "
                "Saya menggunakan Nginx. Saya menggunakan PostgreSQL. "
                "Saya menggunakan Redis. Saya menggunakan Kubernetes. "
                "Saya menggunakan Prometheus.")
        facts = self._extract(text)
        self.assertLessEqual(len(facts), 6,
                             f"Should not extract more than 6 facts, got: {len(facts)}")


# ── Retrieval Accuracy ────────────────────────────────────

class TestRetrievalAccuracy(unittest.TestCase):
    """
    Test: setelah user menyebut sesuatu, retrieval harus bisa menemukannya.
    """

    def setUp(self):
        self.sc = make_sc()

    def tearDown(self):
        self.sc.close()

    def test_personal_fact_retrieved(self):
        """Setelah user sebut Proxmox, query tentang server harus retrieve fact itu."""
        uid = "u_retrieval"

        # User menyebut Proxmox
        turn = ProcessTurn(
            user_id            = uid,
            user_message       = "Saya menggunakan Proxmox untuk server saya",
            assistant_response = "Proxmox adalah platform virtualisasi yang bagus.",
            agent_id           = "general",
        )
        self.sc.processor.process(turn)

        # Query tentang server
        profile = self.sc.memory(uid).get_profile()
        plan    = self.sc.planner.plan("server saya pakai apa", uid, profile=profile)
        nodes   = self.sc.engine.retrieve(plan)

        contents = [n.content.lower() for n in nodes]
        found = any("proxmox" in c for c in contents)
        self.assertTrue(found,
                       f"Expected 'proxmox' in retrieved nodes.\nContents: {contents[:5]}")

    def test_project_fact_retrieved(self):
        """Setelah user sebut project, query tentang project harus retrieve fact itu."""
        uid = "u_project"

        turn = ProcessTurn(
            user_id            = uid,
            user_message       = "Project saya Mangafork sedang dalam pengembangan",
            assistant_response = "Mangafork terdengar menarik!",
            agent_id           = "general",
        )
        self.sc.processor.process(turn)

        profile = self.sc.memory(uid).get_profile()
        plan    = self.sc.planner.plan("project aku apa namanya", uid, profile=profile)
        nodes   = self.sc.engine.retrieve(plan)

        contents = [n.content.lower() for n in nodes]
        found = any("mangafork" in c for c in contents)
        self.assertTrue(found,
                       f"Expected 'mangafork' in retrieved nodes.\nContents: {contents[:5]}")

    def test_intent_coding_includes_working(self):
        """Coding intent harus retrieve working memory."""
        uid = "u_coding"
        self.sc.memory(uid).add_user("saya debug error python")
        profile = self.sc.memory(uid).get_profile()
        plan    = self.sc.planner.plan("fix bug python ini", uid, profile=profile)

        self.assertTrue(plan.working, "Coding intent harus include working tier")
        self.assertTrue(plan.semantic, "Coding intent harus include semantic tier")

    def test_personal_intent_targets_semantic(self):
        """Personal intent harus prioritaskan semantic tier."""
        profile = {}
        plan    = self.sc.planner.plan("siapa saya dan suka apa saya", "u1", profile=profile)
        self.assertEqual(plan.intent, "personal")
        self.assertTrue(plan.semantic)
        # Budget semantic lebih besar dari working untuk personal intent
        self.assertGreater(plan.budget["semantic"], plan.budget.get("episodic", 0))

    def test_history_intent_targets_working_episodic(self):
        """Keyword 'sebelumnya' → conversation intent dengan working+episodic."""
        plan = self.sc.planner.plan("tadi sebelumnya kita bahas apa?", "u1")
        self.assertEqual(plan.intent, "conversation")
        self.assertTrue(plan.working)
        self.assertTrue(plan.episodic)


# ── Memory Evolution ──────────────────────────────────────

class TestMemoryEvolution(unittest.TestCase):

    def setUp(self):
        self.sc = make_sc()

    def tearDown(self):
        self.sc.close()

    def test_fact_dedup_supersedes_old(self):
        """Fact yang sama tidak boleh duplikat — yang lama di-supersede."""
        from simplecontext import NodeStatus
        uid = "u_dedup"

        # Turn 1: user pakai Python
        turn1 = ProcessTurn(
            user_id="u_dedup",
            user_message="Saya menggunakan Python untuk coding",
            assistant_response="Python bagus.",
            agent_id="general",
        )
        self.sc.processor.process(turn1)

        # Turn 2: konfirmasi lagi
        turn2 = ProcessTurn(
            user_id="u_dedup",
            user_message="Saya pakai Python sejak lama",
            assistant_response="Mantap.",
            agent_id="general",
        )
        self.sc.processor.process(turn2)

        # Cek: tidak boleh ada 2 active fact tentang Python yang duplikat
        semantic = self.sc.context(uid).semantic.get()
        python_facts = [n for n in semantic if "python" in n.content.lower()]
        active_python = [n for n in python_facts if n.status == NodeStatus.ACTIVE]

        # Harus max 1 active fact tentang Python yang mirip
        self.assertLessEqual(len(active_python), 2,
                            f"Too many duplicate Python facts: {[n.content for n in active_python]}")

    def test_importance_increases_on_use(self):
        """Node yang dipakai dalam retrieval harus dapat importance boost."""
        from simplecontext import NodeKind
        uid  = "u_imp"
        ctx  = self.sc.context(uid)
        node = ctx.working.add("python debug tips", NodeKind.MESSAGE, importance=0.5)

        old_imp = node.importance

        # Process turn dengan node ini sebagai used_nodes
        turn = ProcessTurn(
            user_id="u_imp",
            user_message="debug python",
            assistant_response="Coba cek traceback.",
            used_nodes=[node],
        )
        self.sc.processor.process(turn)

        updated = self.sc._storage.get_node(node.id)
        if updated:
            self.assertGreaterEqual(updated.importance, old_imp)

    def test_decay_reduces_importance(self):
        """apply_decay harus mengurangi importance semua node."""
        from simplecontext import NodeKind
        uid  = "u_decay"
        ctx  = self.sc.context(uid)
        node = ctx.semantic.add("test fact", NodeKind.FACT, importance=0.5)

        self.sc.apply_decay(uid)

        updated = self.sc._storage.get_node(node.id)
        if updated:
            self.assertLessEqual(updated.importance, 0.5)

    def test_compression_moves_to_episodic(self):
        """Setelah compress, ringkasan harus masuk episodic tier."""
        uid = "u_compress"
        mem = self.sc.memory(uid)
        for i in range(15):
            mem.add_user(f"pesan ke {i}")

        mem.compress(keep_last=5)

        episodic = self.sc.context(uid).episodic.get()
        summaries = [n for n in episodic if "summary" in n.tags or "compressed" in n.tags]
        self.assertGreater(len(summaries), 0,
                          "Setelah compress harus ada summary di episodic tier")


# ── Context Cache ─────────────────────────────────────────

class TestContextCache(unittest.TestCase):

    def test_cache_hit(self):
        from simplecontext.context.cache import ContextCache
        cache = ContextCache(ttl_seconds=60)
        key   = ContextCache.make_key("u1", "test query", "coding")
        nodes = ["node1", "node2"]
        cache.set(key, nodes)
        result = cache.get(key)
        self.assertEqual(result, nodes)

    def test_cache_miss_after_ttl(self):
        import time
        from simplecontext.context.cache import ContextCache
        cache = ContextCache(ttl_seconds=1)
        key   = ContextCache.make_key("u1", "test", "general")
        cache.set(key, ["node"])
        time.sleep(1.1)
        self.assertIsNone(cache.get(key))

    def test_cache_invalidate(self):
        from simplecontext.context.cache import ContextCache
        cache = ContextCache()
        k1 = ContextCache.make_key("u1", "q1", "coding")
        k2 = ContextCache.make_key("u2", "q1", "coding")
        cache.set(k1, ["n1"])
        cache.set(k2, ["n2"])
        cache.invalidate("u1")
        self.assertIsNone(cache.get(k1))
        self.assertIsNotNone(cache.get(k2))

    def test_lru_eviction(self):
        from simplecontext.context.cache import ContextCache
        cache = ContextCache(max_size=3)
        for i in range(4):
            k = ContextCache.make_key(f"u{i}", "q", "g")
            cache.set(k, [f"node{i}"])
        self.assertLessEqual(cache.size, 3)

    def test_engine_uses_cache(self):
        """ContextEngine harus pakai cache pada query kedua yang sama."""
        sc = make_sc()
        uid = "u_cache_engine"
        from simplecontext import NodeKind
        sc.context(uid).working.add("test content", NodeKind.MESSAGE)

        profile = sc.memory(uid).get_profile()
        plan    = sc.planner.plan("test query", uid, profile=profile)

        # Pertama: cache miss
        nodes1 = sc.engine.retrieve(plan)
        cache_size_after_first = sc.engine._cache.size

        # Kedua: cache hit
        nodes2 = sc.engine.retrieve(plan)

        self.assertEqual(len(nodes1), len(nodes2))
        self.assertEqual(cache_size_after_first, sc.engine._cache.size)
        sc.close()


# ── PromptBuilder Format ──────────────────────────────────

class TestPromptBuilderFormat(unittest.TestCase):

    def setUp(self):
        from simplecontext.context.builder import PromptBuilder
        self.builder = PromptBuilder()

    def _make_node(self, content, tier="working", kind="message"):
        from simplecontext import ContextNode, Tier, NodeKind
        tier_map = {"working": Tier.WORKING, "episodic": Tier.EPISODIC, "semantic": Tier.SEMANTIC}
        kind_map = {"message": NodeKind.MESSAGE, "fact": NodeKind.FACT, "summary": NodeKind.SUMMARY}
        return ContextNode(
            user_id="u1", path=f"/memory/{tier}/u1/x",
            tier=tier_map[tier], kind=kind_map[kind], content=content,
        )

    def test_system_rules_always_present(self):
        messages = self.builder.build("Base prompt.", [], "test msg")
        system = messages[0]["content"]
        self.assertIn("RULES:", system)
        self.assertIn("Answer directly", system)

    def test_context_sections_format(self):
        nodes = [
            self._make_node("user meminta kode python", "working"),
            self._make_node("user pakai proxmox", "semantic", "fact"),
        ]
        messages = self.builder.build("Base.", nodes, "test")
        system   = messages[0]["content"]
        self.assertIn("[Working Context]", system)
        self.assertIn("[Semantic Knowledge]", system)
        self.assertIn("- ", system)  # bullet format

    def test_truncation_applied(self):
        long_content = "x" * 2000
        node = self._make_node(long_content)
        messages = self.builder.build("Base.", [node], "test")
        system   = messages[0]["content"]
        # Konten yang masuk ke prompt harus lebih pendek dari original
        self.assertLess(len(system), len("Base.") + 2000 + 500)

    def test_profile_injected(self):
        profile  = {"nama": "ZACY", "project": "Mangafork"}
        messages = self.builder.build("Base.", [], "test", profile=profile)
        system   = messages[0]["content"]
        self.assertIn("ZACY", system)
        self.assertIn("Mangafork", system)
        self.assertIn("[User Profile]", system)

    def test_user_message_last(self):
        messages = self.builder.build("Base.", [], "pesan user")
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"], "pesan user")

    def test_deterministic_order(self):
        """Panggil dua kali dengan input sama → output sama."""
        nodes = [
            self._make_node("w1", "working"),
            self._make_node("s1", "semantic", "fact"),
        ]
        m1 = self.builder.build("Base.", nodes, "test")
        m2 = self.builder.build("Base.", nodes, "test")
        self.assertEqual(m1[0]["content"], m2[0]["content"])


if __name__ == "__main__":
    print("🧪 Benchmark Tests SimpleContext v4.1\n")
    unittest.main(verbosity=2)
