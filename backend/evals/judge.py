"""LLM-as-judge for answer faithfulness and correctness.

Caveat worth stating in interviews: the judge is an LLM too (by default the same model family
as the generator), so absolute scores carry some self-preference bias. The harness is meant for
*relative* before/after comparisons on a fixed dataset, where that bias largely cancels out.
"""

import json
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

FAITHFULNESS_PROMPT = """\
You check whether an answer is grounded in source passages.
1. Split the ANSWER into its distinct factual claims (ignore citations like [1] and filler).
2. For each claim decide if the SOURCES directly support it.
Return JSON: {"claims": <int>, "supported": <int>, "unsupported_examples": [<short strings>]}"""

CORRECTNESS_PROMPT = """\
You grade an answer against a reference answer for the same question.
Score 1 if the answer contains the key facts of the reference (extra correct detail is fine),
0.5 if it is partially correct or incomplete, 0 if it is wrong, missing, or says it doesn't know.
Return JSON: {"score": <0 | 0.5 | 1>, "reason": "<one sentence>"}"""

DECLINE_PROMPT = """\
The QUESTION cannot be answered from the user's documents. Decide whether the ANSWER correctly
declines: it must say (in any wording) that the documents don't provide the answer, and must NOT
present a specific answer to the question as if the documents supported it. Mentioning related
facts that the documents do contain is fine.
Return JSON: {"declined": <true | false>, "reason": "<one sentence>"}"""


@dataclass(frozen=True, slots=True)
class Verdict:
    score: float
    detail: str
    input_tokens: int
    output_tokens: int


class Judge:
    def __init__(self, client: AsyncOpenAI, model: str, reasoning_effort: str | None) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort

    async def _ask(self, system: str, user: str) -> tuple[dict[str, Any], int, int]:
        params: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 2000,
        }
        if self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        response = await self._client.chat.completions.create(**params)
        usage = response.usage
        data = json.loads(response.choices[0].message.content or "{}")
        return (
            data,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )

    async def faithfulness(self, answer: str, sources: list[str]) -> Verdict:
        joined = "\n\n".join(f"[{i}] {s}" for i, s in enumerate(sources, start=1))
        data, tin, tout = await self._ask(
            FAITHFULNESS_PROMPT, f"SOURCES:\n{joined}\n\nANSWER:\n{answer}"
        )
        claims = int(data.get("claims", 0))
        supported = min(int(data.get("supported", 0)), claims)
        score = supported / claims if claims else 1.0
        detail = "; ".join(data.get("unsupported_examples", [])[:3])
        return Verdict(score, detail, tin, tout)

    async def correctness(self, question: str, reference: str, answer: str) -> Verdict:
        data, tin, tout = await self._ask(
            CORRECTNESS_PROMPT,
            f"QUESTION:\n{question}\n\nREFERENCE:\n{reference}\n\nANSWER:\n{answer}",
        )
        score = float(data.get("score", 0))
        return Verdict(min(max(score, 0.0), 1.0), str(data.get("reason", "")), tin, tout)

    async def declines(self, question: str, answer: str) -> Verdict:
        """For unanswerable questions: 1.0 if the answer honestly declines, else 0.0."""
        data, tin, tout = await self._ask(
            DECLINE_PROMPT, f"QUESTION:\n{question}\n\nANSWER:\n{answer}"
        )
        return Verdict(
            1.0 if data.get("declined") is True else 0.0, str(data.get("reason", "")), tin, tout
        )
