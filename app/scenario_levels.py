"""The three conversation levels. The rules are added to the AI's instructions for every reply."""

LEVELS = [
    {
        "id": "beginner",
        "label": "Beginner",
        "cefr": "A1-A2",
        "description": "Short, simple sentences and a slow pace, with hints when you get stuck.",
        "rules": (
            "LEVEL: BEGINNER (A1-A2). Use very short, simple sentences (at most 8 words), the present tense and "
            "common everyday words. Speak slowly and clearly. If the user seems stuck, ask the question again more "
            "simply. In your one-line English feedback, add a simple German sentence the user could have said. "
            "Judge the answer against a beginner: reward any understandable attempt."
        ),
    },
    {
        "id": "intermediate",
        "label": "Intermediate",
        "cefr": "B1",
        "description": "Natural everyday German with follow-up questions and a few complications.",
        "rules": (
            "LEVEL: INTERMEDIATE (B1). Speak naturally at an everyday pace, using past tenses and connectors such as "
            "weil, dass and obwohl. Ask a follow-up question and add one small complication. Only point out clear "
            "mistakes. Judge the answer against a B1 learner."
        ),
    },
    {
        "id": "professional",
        "label": "Professional",
        "cefr": "B2-C1",
        "description": "Formal, precise German with idioms, official wording and real-world pushback.",
        "rules": (
            "LEVEL: PROFESSIONAL (B2-C1). Use formal, precise German (Sie form), subordinate clauses, idioms and the "
            "vocabulary of the situation. Be realistic and a little demanding: raise objections, ask for details and "
            "add unexpected complications. Do not simplify unless the user asks. Judge the answer strictly for "
            "grammar, politeness and word choice."
        ),
    },
]

LEVEL_IDS = [level["id"] for level in LEVELS]
