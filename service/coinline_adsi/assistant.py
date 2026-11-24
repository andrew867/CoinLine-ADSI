"""Optional answers scoped to a small, reviewed public glossary."""

import asyncio
import json
import os
import time
from collections import deque
from urllib.parse import urlsplit

import httpx


GLOSSARY = {
    "adsi": (
        "What is ADSI?",
        "Analog Display Services Interface sends display text and softkey definitions over the audio path of a telephone call.",
    ),
    "weather": (
        "How is my weather location selected?",
        "A phone number prefix suggests an assigned exchange. The caller can choose a different weather location.",
    ),
}
SOURCE = "CoinLine glossary"


class InformationDesk:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.endpoint = os.getenv("ADSI_MODEL_URL", "")
        self.model = os.getenv("ADSI_MODEL_NAME", "")
        self.key = os.getenv("ADSI_MODEL_KEY", "")
        self.attempts = deque()
        self.capacity = asyncio.Semaphore(2)

    async def answer(self, key: str) -> dict | None:
        if key not in GLOSSARY:
            return None
        question, excerpt = GLOSSARY[key]
        if not self.endpoint or not self.model:
            return {"answer": excerpt, "source": SOURCE, "displayTitle": "GLOSSARY"}
        target = urlsplit(self.endpoint)
        if (target.scheme != "https" or not target.hostname or target.username is not None or
                target.query or target.fragment or not target.path.endswith("/chat/completions")):
            return None
        now = time.monotonic()
        while self.attempts and self.attempts[0] < now - 60:
            self.attempts.popleft()
        if len(self.attempts) >= 30 or self.capacity.locked():
            return None
        self.attempts.append(now)
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        try:
            async with self.capacity, asyncio.timeout(5):
                async with self.client.stream("POST", self.endpoint, headers=headers, json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "Answer using only the source text. Return a JSON object with "
                         "one field named answer, no more than 120 characters. Return an empty answer if the source "
                         "does not answer the question."},
                        {"role": "user", "content": json.dumps({"question": question, "public_source": excerpt})},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 96,
                }, follow_redirects=False) as response:
                    response.raise_for_status()
                    buffer = bytearray()
                    async for piece in response.aiter_bytes():
                        buffer.extend(piece)
                        if len(buffer) > 8192:
                            return None
                payload = json.loads(buffer)
            result = json.loads(payload["choices"][0]["message"]["content"])
            if isinstance(result, dict) and set(result) == {"answer"}:
                answer = result["answer"]
                if isinstance(answer, str) and 1 <= len(answer.strip()) <= 120 and answer.isprintable():
                    return {"answer": answer, "source": SOURCE, "displayTitle": "INFO DESK"}
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError, IndexError):
            pass
        return None
