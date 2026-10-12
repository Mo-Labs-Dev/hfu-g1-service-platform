from __future__ import annotations

import json
import os
import re

import httpx


OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434",
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "g1-assistant",
)

G1_SPEECH_URL = os.getenv(
    "G1_SPEECH_URL",
    "http://127.0.0.1:8766",
)

SYSTEM_CONTEXT = """
You are G1, the physical Unitree G1 humanoid robot
research prototype at Furtwangen University, Germany.

You are part of a master's thesis researching interactive
visitor assistance, laboratory guidance and demonstrations.

Verified information:
- You are a Unitree G1 robot at Furtwangen University.
- You are connected to the G1 Studio platform.
- Your built-in speaker has been tested successfully.
- Your Livox MID-360 LiDAR provides live 3D point clouds.
- Autonomous guidance and object manipulation are
  still under development.

You are speaking directly to a visitor.

IMPORTANT:
- Return only the answer you would say aloud.
- Never describe your reasoning or planning.
- Never analyze the visitor's wording.
- Never say "the user asked" or "I should respond".
- Use first-person speech as G1.
- Keep answers friendly, factual and concise.
- Usually respond in 1 to 3 short sentences.
- Don't invent laboratory details or robot abilities.
- You cannot execute physical robot actions.
- Do not use Markdown or reasoning tags.
- Return a JSON object containing only an "answer" string.
"""

REASONING_PATTERNS = (
    r"\bthe user (said|asked|wants|greeted|might)\b",
    r"\blet me (think|recall|consider|analyze)\b",
    r"\bi (should|need to) (respond|mention|state|explain)\b",
    r"\bfirst,? i (should|need)\b",
    r"\bmy (reasoning|analysis|thought process)\b",
    r"<think>",
    r"</think>",
)


def validate_answer(text: str) -> str:
    text = text.strip()

    if not text:
        raise RuntimeError("The AI returned an empty answer")

    if any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in REASONING_PATTERNS
    ):
        raise RuntimeError(
            "The AI returned reasoning instead of a spoken answer"
        )

    text = re.sub(r"\s+", " ", text)

    if len(text) > 450:
        shortened = text[:450]

        sentence_end = max(
            shortened.rfind("."),
            shortened.rfind("!"),
            shortened.rfind("?"),
        )

        if sentence_end > 40:
            text = shortened[:sentence_end + 1]
        else:
            text = shortened.rsplit(" ", 1)[0].rstrip(" ,;:")

    return text


class InteractionService:
    async def ask(
        self,
        question: str,
        speak: bool = False,
    ) -> dict:
        question = question.strip()

        if not question:
            raise ValueError("Question cannot be empty")

        if len(question) > 1000:
            raise ValueError("Question is too long")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "stream": False,
                    "think": False,
                    "messages": [
                        {
                            "role": "system",
                            "content": SYSTEM_CONTEXT,
                        },
                        {
                            "role": "user",
                            "content": (
                                "/no_think\n"
                                + question
                            ),
                        },
                    ],
                    "format": {
                        "type": "object",
                        "properties": {
                            "answer": {
                                "type": "string",
                            },
                        },
                        "required": ["answer"],
                        "additionalProperties": False,
                    },
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": 4096,
                        "num_predict": 250,
                    },
                },
            )

            response.raise_for_status()
            result = response.json()

        content = result.get("message", {}).get(
            "content", ""
        )

        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError(
                "AI did not return a valid answer"
            ) from error

        if not isinstance(parsed, dict):
            raise RuntimeError("Invalid AI response")

        raw_answer = parsed.get("answer")

        if not isinstance(raw_answer, str):
            raise RuntimeError("Missing AI answer")

        answer = validate_answer(raw_answer)

        speech_accepted = False
        speech_error = None

        if speak:
            try:
                async with httpx.AsyncClient(
                    timeout=20.0
                ) as client:
                    speech_response = await client.post(
                        f"{G1_SPEECH_URL}/speak",
                        json={"text": answer},
                    )

                    speech_response.raise_for_status()

                    speech_accepted = bool(
                        speech_response.json().get(
                            "accepted", False
                        )
                    )

            except (httpx.HTTPError, ValueError) as error:
                speech_error = str(error)

        return {
            "question": question,
            "answer": answer,
            "model": OLLAMA_MODEL,
            "speech_accepted": speech_accepted,
            "speech_error": speech_error,
        }


interaction_service = InteractionService()