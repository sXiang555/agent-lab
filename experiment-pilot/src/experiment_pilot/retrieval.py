from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass

import httpx
import psycopg
from openai import OpenAI

from .catalog import DATA
from .config import Settings

TOKENS = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*|[\u3400-\u9fff]", re.I)
HEADING = re.compile(r"^## \[([a-z0-9-]+)\] (.+)$", re.M)


@dataclass(frozen=True)
class Chunk:
    source_id: str
    title: str
    text: str


def _tokens(text: str) -> list[str]:
    return TOKENS.findall(text.lower())


def _hash_vector(text: str) -> list[float]:
    vector = [0.0] * 256
    words = _tokens(text)
    for feature in [*words, *(a + "|" + b for a, b in zip(words, words[1:]))]:
        digest = hashlib.blake2s(feature.encode(), digest_size=4).digest()
        index = int.from_bytes(digest, "big")
        vector[index % len(vector)] += 1 if index & 256 else -1
    return vector


def _cosine(left: list[float], right: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right, strict=True)) / norm if norm else 0.0


class Retriever:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        text = DATA.joinpath("handbook.md").read_text(encoding="utf-8")
        sections = list(HEADING.finditer(text))
        self.chunks = {
            f"kb:{part[1]}": Chunk(f"kb:{part[1]}", part[2], " ".join(
                text[part.end(): sections[index + 1].start() if index + 1 < len(sections) else None]
                .split()
            ))
            for index, part in enumerate(sections)
        }
        self.word_counts = {
            key: Counter(_tokens(f"{chunk.title} {chunk.text}"))
            for key, chunk in self.chunks.items()
        }
        self.average_length = sum(c.total() for c in self.word_counts.values()) / len(self.chunks)
        self.document_freq = Counter(word for counts in self.word_counts.values() for word in counts)
        self.embedding = (
            OpenAI(api_key=settings.model_key, base_url=settings.model_base_url or None,
                   max_retries=1, timeout=12)
            if settings.embedding_model else None
        )
        self._vectors = {}
        if settings.database_url:
            self._index_pg()
        else:
            self._vectors = dict(zip(self.chunks, self._embed([
                self._chunk_text(chunk) for chunk in self.chunks.values()
            ]), strict=True))

    @staticmethod
    def _chunk_text(chunk: Chunk) -> str:
        return f"{chunk.title}\n{chunk.text}"

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.embedding is not None:
            response = self.embedding.embeddings.create(
                model=self.settings.embedding_model, input=texts, encoding_format="float"
            )
            return [row.embedding for row in sorted(response.data, key=lambda row: row.index)]
        return [_hash_vector(text) for text in texts]

    def _index_pg(self) -> None:
        identity = self.settings.embedding_model or "hash-vector-256-v1"
        fingerprints = {
            key: hashlib.sha256(f"{identity}\n{self._chunk_text(chunk)}".encode()).hexdigest()
            for key, chunk in self.chunks.items()
        }
        with psycopg.connect(self.settings.database_url) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pilot_chunks (
                    source_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, embedding VECTOR NOT NULL
                )
            """)
            old = dict(conn.execute("SELECT source_id, fingerprint FROM pilot_chunks").fetchall())
            changed = [key for key in self.chunks if old.get(key) != fingerprints[key]]
            embeddings = self._embed([self._chunk_text(self.chunks[key]) for key in changed])
            for key, vector in zip(changed, embeddings, strict=True):
                conn.execute("""
                    INSERT INTO pilot_chunks VALUES (%s, %s, %s::vector)
                    ON CONFLICT (source_id) DO UPDATE SET
                        fingerprint = EXCLUDED.fingerprint, embedding = EXCLUDED.embedding
                """, (key, fingerprints[key], json.dumps(vector)))
            conn.execute("DELETE FROM pilot_chunks WHERE NOT (source_id = ANY(%s))",
                         (list(self.chunks),))

    def _dense(self, query: str) -> list[str]:
        vector = self._embed([query])[0]
        if not any(vector):
            return []
        if self.settings.database_url:
            with psycopg.connect(self.settings.database_url) as conn:
                rows = conn.execute("""
                    SELECT source_id, embedding <=> %s::vector AS distance FROM pilot_chunks
                    ORDER BY distance, source_id LIMIT 8
                """, (json.dumps(vector),)).fetchall()
            return [key for key, distance in rows if distance < 1.0]
        scores = [(key, _cosine(vector, val)) for key, val in self._vectors.items()]
        return [key for key, score in sorted(scores, key=lambda pair: (-pair[1], pair[0]))
                if score > 0][:8]

    def _bm25(self, words: set[str], key: str) -> float:
        counts = self.word_counts[key]
        norm = 1.5 * (0.25 + 0.75 * counts.total() / self.average_length)
        score = 0.0
        for word in words & counts.keys():
            freq = self.document_freq[word]
            idf = math.log1p((len(self.chunks) - freq + 0.5) / (freq + 0.5))
            score += idf * (counts[word] * 2.5) / (counts[word] + norm)
        return score

    def _rerank(self, query: str, keys: list[str], limit: int) -> list[str]:
        if self.settings.rerank_url:
            headers = ({"Authorization": f"Bearer {self.settings.rerank_key}"}
                       if self.settings.rerank_key else {})
            response = httpx.post(self.settings.rerank_url, headers=headers, timeout=12, json={
                "model": self.settings.rerank_model,
                "query": query,
                "documents": [self._chunk_text(self.chunks[key]) for key in keys],
                "top_n": min(limit, len(keys)),
            })
            response.raise_for_status()
            indexes = [item["index"] for item in response.json()["results"]]
            if any(type(index) is not int or not 0 <= index < len(keys) for index in indexes):
                raise ValueError("Rerank provider returned an invalid document index")
            return [keys[index] for index in dict.fromkeys(indexes)][:limit]
        words = set(_tokens(query))
        return sorted(keys, key=lambda key: -len(words & set(_tokens(self.chunks[key].title))))[:limit]

    def get(self, source_id: str) -> dict:
        return asdict(self.chunks[source_id])

    def search(self, query: str, limit: int = 3) -> list[dict]:
        words = set(_tokens(query))
        if not words:
            return []
        bm25 = sorted(((key, self._bm25(words, key)) for key in self.chunks),
                      key=lambda pair: (-pair[1], pair[0]))
        lexical = [key for key, score in bm25 if score > 0][:8]
        fused: Counter[str] = Counter()
        for ranking in (lexical, self._dense(query)):
            for rank, key in enumerate(ranking, start=1):
                fused[key] += 1 / (60 + rank)
        candidates = [key for key, _ in fused.most_common(6)]
        if not candidates:
            return []
        return [asdict(self.chunks[key]) for key in self._rerank(query, candidates, limit)]
