import os
import time
import requests
from dotenv import load_dotenv
from google import genai


# ============================================================
# SETUP
# ============================================================

load_dotenv()

gemini_client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

MAX_IMPROVEMENT_ROUNDS = 3
MAX_APPROVAL_ROUNDS = 3
MAX_CONTEXT_TURNS = 10

OPENROUTER_MAX_RETRIES = 4


# ============================================================
# AGENT 1 — GEMINI
# ============================================================

def ask_gemini(prompt):

    response = gemini_client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt
    )

    if not response.text:
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    return response.text.strip()


# ============================================================
# AGENT 2 — OPENROUTER
# ============================================================

def ask_openrouter(prompt):

    for attempt in range(OPENROUTER_MAX_RETRIES):

        try:

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",

                headers={
                    "Authorization": (
                        f"Bearer {os.getenv('OPENROUTER_API_KEY')}"
                    ),
                    "Content-Type": "application/json"
                },

                json={
                    "model": "openrouter/free",

                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                },

                timeout=120
            )

            # ------------------------------------------------
            # RATE LIMIT — HTTP 429
            # ------------------------------------------------

            if response.status_code == 429:

                if attempt < OPENROUTER_MAX_RETRIES - 1:

                    wait_time = 5 * (2 ** attempt)

                    print(
                        "\n[OpenRouter] Rate limit reached."
                    )

                    print(
                        f"[OpenRouter] Retrying in "
                        f"{wait_time} seconds..."
                    )

                    time.sleep(wait_time)

                    continue

                raise RuntimeError(
                    "OpenRouter is still rate-limited after "
                    "multiple attempts."
                )

            # ------------------------------------------------
            # OTHER HTTP ERRORS
            # ------------------------------------------------

            response.raise_for_status()

            # ------------------------------------------------
            # READ RESPONSE
            # ------------------------------------------------

            data = response.json()

            content = (
                data
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content")
            )

            if not content:

                raise RuntimeError(
                    "OpenRouter returned an empty response."
                )

            return content.strip()

        except requests.exceptions.Timeout:

            if attempt < OPENROUTER_MAX_RETRIES - 1:

                wait_time = 5 * (2 ** attempt)

                print(
                    "\n[OpenRouter] Request timed out."
                )

                print(
                    f"[OpenRouter] Retrying in "
                    f"{wait_time} seconds..."
                )

                time.sleep(wait_time)

            else:

                raise RuntimeError(
                    "OpenRouter request timed out after "
                    "multiple attempts."
                )

        except requests.exceptions.RequestException as error:

            if attempt < OPENROUTER_MAX_RETRIES - 1:

                wait_time = 5 * (2 ** attempt)

                print(
                    "\n[OpenRouter] Request failed."
                )

                print(
                    f"[OpenRouter] Retrying in "
                    f"{wait_time} seconds..."
                )

                time.sleep(wait_time)

            else:

                raise RuntimeError(
                    f"OpenRouter request failed: {error}"
                )

    raise RuntimeError(
        "OpenRouter request failed."
    )


# ============================================================
# CONVERSATION CONTEXT
# ============================================================

def format_conversation_history(conversation_history):

    if not conversation_history:
        return "No previous conversation."

    recent_history = conversation_history[
        -MAX_CONTEXT_TURNS:
    ]

    formatted = []

    for item in recent_history:

        formatted.append(
            f"USER:\n{item['user']}\n\n"
            f"AI TEAM:\n{item['assistant']}"
        )

    return (
        "\n\n"
        "--- PREVIOUS TURN ---"
        "\n\n"
    ).join(formatted)


# ============================================================
# FIND IMPROVEMENTS
# ============================================================

def find_improvements(
    agent_name,
    question,
    own_answer,
    other_answer,
    conversation_context
):

    prompt = f"""
You are {agent_name}, an equal member of a two-agent AI team.

You are helping answer the user's CURRENT question.

CURRENT USER QUESTION:
{question}

RELEVANT PREVIOUS CONVERSATION:
{conversation_context}

YOUR CURRENT ANSWER:
{own_answer}

OTHER AGENT'S CURRENT ANSWER:
{other_answer}

Your job is NOT to simply approve your answer.

Your job is to aggressively search for genuine ways to make your answer
better for THIS user and THIS question.

Think deeply about the actual question, the previous conversation,
your answer, and the other agent's answer.

Look for:

1. Factual errors
2. Missing important information
3. Incorrect or weak reasoning
4. Contradictions
5. Misleading statements
6. Incomplete explanations
7. Unclear explanations
8. Poor organization
9. Unnecessary information
10. Repetition
11. Better examples that genuinely improve understanding
12. Important edge cases
13. Important assumptions
14. Whether the answer satisfies the user's actual intention
15. Whether something from the other agent's answer is genuinely
    better and should be incorporated
16. Whether the answer is unnecessarily technical or verbose

IMPORTANT QUALITY RULE:

Do NOT improve the answer merely by adding more information.

For every possible improvement, ask:

"Would this genuinely make the answer more useful to THIS user
for THIS question?"

If the answer is no, do not recommend it.

Prefer the minimum amount of information needed to give an excellent,
accurate and useful answer.

IMPORTANT:

- Do not invent problems just to make a change.
- Do not change correct information merely for stylistic preference.
- Do not make the answer longer without a useful reason.
- Do not make the answer shorter if that removes important information.
- Preserve strong parts of your existing answer.
- If the other agent has useful information, consider incorporating it.
- If the other agent is wrong, do NOT copy it.
- Use your own reasoning to decide what is actually correct.
- Do not add advanced information merely because it is technically
  interesting.
- Do not repeat information the user already understands.
- Focus on QUALITY, not QUANTITY.

Think like a perfectionist teammate:

"What can I genuinely improve in my answer after seeing the other
agent's answer?"

Return ONLY one of these two formats:

IMPROVEMENTS:
1. specific genuine improvement
2. specific genuine improvement

OR exactly:

NO_MEANINGFUL_IMPROVEMENT
"""

    if agent_name == "Gemini":
        result = ask_gemini(prompt)
    else:
        result = ask_openrouter(prompt)

    if not result:
        return "NO_MEANINGFUL_IMPROVEMENT"

    return result.strip()


# ============================================================
# APPLY IMPROVEMENTS
# ============================================================

def apply_improvements(
    agent_name,
    question,
    current_answer,
    other_answer,
    improvement_points,
    conversation_context
):

    prompt = f"""
You are {agent_name}, an equal member of a two-agent AI team.

CURRENT USER QUESTION:
{question}

RELEVANT PREVIOUS CONVERSATION:
{conversation_context}

YOUR CURRENT ANSWER:
{current_answer}

OTHER AGENT'S ANSWER:
{other_answer}

YOUR IDENTIFIED IMPROVEMENTS:
{improvement_points}

Now produce a genuinely improved version of your answer.

Rules:

- Fix genuine factual problems.
- Add genuinely important missing information.
- Improve weak reasoning.
- Improve unclear explanations.
- Incorporate useful information from the other agent when appropriate.
- Resolve contradictions using your own reasoning.
- Remove unnecessary repetition.
- Remove information that does not help answer the user's question.
- Keep correct information that is already strong.
- Do NOT blindly apply an improvement if it is actually wrong.
- Do NOT add information just to make the answer longer.
- Do NOT add advanced details merely because they are interesting.
- Do NOT remove useful information just to make it shorter.
- Keep the level of detail appropriate to the actual question.
- Use previous conversation when it genuinely helps.
- Do not unnecessarily repeat previous answers.
- Make the answer clear, natural, accurate and useful.
- Answer the user's actual intention.
- Do not mention this collaboration.
- Do not mention the other agent.
- Do not describe what you changed.

IMPORTANT:

Quality is more important than quantity.

Return ONLY the improved answer.
"""

    if agent_name == "Gemini":
        result = ask_gemini(prompt)
    else:
        result = ask_openrouter(prompt)

    if not result:
        return current_answer

    return result.strip()


# ============================================================
# CREATE TEAM DRAFT
# ============================================================

def create_team_draft(
    question,
    answer1,
    answer2,
    conversation_context
):

    prompt = f"""
You are creating a shared TEAM DRAFT from two equal AI teammates.

CURRENT USER QUESTION:
{question}

RELEVANT PREVIOUS CONVERSATION:
{conversation_context}

AGENT 1 ANSWER:
{answer1}

AGENT 2 ANSWER:
{answer2}

Create ONE high-quality answer for the user.

Think carefully before writing.

Your job is NOT to mechanically combine both answers.

Instead:

- Identify the strongest correct information from both.
- Resolve contradictions.
- Remove duplicate information.
- Preserve every important point.
- Correct factual problems.
- Reject incorrect information from either agent.
- Include examples when they genuinely help.
- Keep the answer focused on the user's actual intention.
- Use previous conversation when it is relevant.
- Avoid unnecessary verbosity.
- Do not omit important information merely to be concise.
- Do not add technically interesting information unless it helps
  answer the actual question.
- Keep the depth proportional to what the user needs.
- Make the result natural and easy to understand.
- Do not mention the agents.
- Do not mention collaboration.
- Do not say "Agent 1 says..." or "Agent 2 says..."

QUALITY TEST:

Before including a sentence, ask:

"Does this sentence genuinely help the user understand or answer
their current question?"

If not, leave it out.

The final draft should feel like ONE excellent answer written directly
for the user.

Return ONLY the team draft.
"""

    result = ask_gemini(prompt)

    if not result:
        raise RuntimeError(
            "Team draft generation returned an empty response."
        )

    return result.strip()


# ============================================================
# TEAM DRAFT REVIEW
# ============================================================

def review_team_draft(
    agent_name,
    question,
    team_draft,
    conversation_context
):

    prompt = f"""
You are {agent_name}, one of two equal AI teammates.

The following is the EXACT SAME TEAM DRAFT that the user may receive.

CURRENT USER QUESTION:
{question}

RELEVANT PREVIOUS CONVERSATION:
{conversation_context}

TEAM DRAFT:
{team_draft}

Now aggressively inspect this draft.

Do NOT just approve it because it looks good.

Search carefully for every meaningful problem that could reduce its
quality.

Check:

- factual accuracy
- logical correctness
- completeness
- missing important information
- contradictions
- misleading claims
- unclear explanations
- poor structure
- unnecessary verbosity
- unnecessary repetition
- inappropriate technical depth
- unnecessary advanced information
- weak examples
- missing examples where one is genuinely needed
- whether it actually answers the user's intention
- whether previous conversation is handled correctly
- whether any statement should be corrected or qualified

IMPORTANT:

Do not request changes merely because you personally prefer different
wording.

Do not request extra information simply because it is technically
interesting.

Only identify changes that would genuinely make the answer better
for THIS user and THIS question.

If there are genuine problems, return:

REVISE:
1. specific problem and useful correction
2. specific problem and useful correction

If after serious inspection the draft has no meaningful problems,
return exactly:

APPROVED

Do not rewrite the draft.
"""

    # --------------------------------------------------------
    # IMPORTANT FIX:
    # Always store the response first.
    # If the API gives nothing, return a safe review.
    # --------------------------------------------------------

    if agent_name == "Gemini":
        result = ask_gemini(prompt)
    else:
        result = ask_openrouter(prompt)

    if not result:
        return (
            "REVISE:\n"
            "The review service did not return a response."
        )

    return result.strip()


# ============================================================
# REVISE TEAM DRAFT
# ============================================================

def revise_team_draft(
    question,
    current_draft,
    gemini_review,
    openrouter_review,
    revision_agent,
    conversation_context
):

    prompt = f"""
You are {revision_agent}, revising a shared answer created by two equal
AI teammates.

CURRENT USER QUESTION:
{question}

RELEVANT PREVIOUS CONVERSATION:
{conversation_context}

CURRENT TEAM DRAFT:
{current_draft}

GEMINI REVIEW:
{gemini_review}

OPENROUTER REVIEW:
{openrouter_review}

Create the next version of the team draft.

Use the reviews as evidence, but think for yourself.

Rules:

- Fix genuine problems identified by the reviews.
- Do not blindly follow a review if it is incorrect.
- Preserve correct information.
- Add missing important information.
- Remove unnecessary information.
- Resolve contradictions.
- Improve clarity where genuinely needed.
- Keep the answer natural.
- Keep the answer focused on the current question.
- Do not make it longer without a reason.
- Do not add advanced information merely because it is interesting.
- Do not make it shorter if important information would be lost.
- Do not introduce unrelated information.
- Use previous conversation only when relevant.
- Do not mention the reviews.
- Do not mention the agents.
- Do not describe the revision process.

QUALITY TEST:

The goal is NOT to maximize the amount of information.

The goal is to produce the most useful answer for the user's actual
question.

Return ONLY the revised team draft.
"""

    if revision_agent == "Gemini":
        result = ask_gemini(prompt)
    else:
        result = ask_openrouter(prompt)

    if not result:
        return current_draft

    return result.strip()


# ============================================================
# ANSWER ONE QUESTION
# ============================================================

def answer_question(
    question,
    conversation_history
):

    conversation_context = format_conversation_history(
        conversation_history
    )

    # ========================================================
    # STEP 1 — INDEPENDENT THINKING
    # ========================================================

    print("\n" + "=" * 60)
    print("STEP 1 — INDEPENDENT THINKING")
    print("=" * 60)

    answer1_prompt = f"""
You are Agent 1, an independent member of an AI team.

CURRENT USER QUESTION:
{question}

RELEVANT PREVIOUS CONVERSATION:
{conversation_context}

Answer the user's current question independently.

Use previous conversation only when it is relevant.

Priorities:

- Accuracy
- Relevance
- Completeness
- Clear reasoning
- Natural language
- Useful structure
- Appropriate detail
- Quality over quantity

Do not unnecessarily repeat previous answers.

Do not mention the AI team.
Do not mention collaboration.

Return ONLY the answer.
"""

    answer2_prompt = f"""
You are Agent 2, an independent member of an AI team.

CURRENT USER QUESTION:
{question}

RELEVANT PREVIOUS CONVERSATION:
{conversation_context}

Answer the user's current question independently.

Use previous conversation only when it is relevant.

Priorities:

- Accuracy
- Relevance
- Completeness
- Clear reasoning
- Natural language
- Useful structure
- Appropriate detail
- Quality over quantity

Do not unnecessarily repeat previous answers.

Do not mention the AI team.
Do not mention collaboration.

Return ONLY the answer.
"""

    answer1 = ask_gemini(answer1_prompt)

    print("\n--- AGENT 1 — GEMINI ---")
    print(answer1)

    answer2 = ask_openrouter(answer2_prompt)

    print("\n--- AGENT 2 — OPENROUTER ---")
    print(answer2)

    # ========================================================
    # STEP 2 — ACTIVE IMPROVEMENT LOOP
    # ========================================================

    for round_number in range(
        1,
        MAX_IMPROVEMENT_ROUNDS + 1
    ):

        print("\n" + "=" * 60)
        print(
            f"STEP 2 — IMPROVEMENT ROUND {round_number}"
        )
        print("=" * 60)

        # ----------------------------------------------------
        # Both agents inspect the SAME previous state.
        # ----------------------------------------------------

        previous_answer1 = answer1
        previous_answer2 = answer2

        gemini_improvements = find_improvements(
            "Gemini",
            question,
            previous_answer1,
            previous_answer2,
            conversation_context
        )

        openrouter_improvements = find_improvements(
            "OpenRouter",
            question,
            previous_answer2,
            previous_answer1,
            conversation_context
        )

        print(
            "\n--- GEMINI: WHAT CAN I IMPROVE? ---"
        )

        print(gemini_improvements)

        print(
            "\n--- OPENROUTER: WHAT CAN I IMPROVE? ---"
        )

        print(openrouter_improvements)

        # ----------------------------------------------------
        # If both find nothing meaningful, stop.
        # ----------------------------------------------------

        if (
            "NO_MEANINGFUL_IMPROVEMENT"
            in gemini_improvements.upper()
            and
            "NO_MEANINGFUL_IMPROVEMENT"
            in openrouter_improvements.upper()
        ):

            print(
                "\nBOTH AGENTS FOUND NO MEANINGFUL IMPROVEMENT."
            )

            break

        # ----------------------------------------------------
        # Both improve from SAME previous state.
        # ----------------------------------------------------

        improved_answer1 = apply_improvements(
            "Gemini",
            question,
            previous_answer1,
            previous_answer2,
            gemini_improvements,
            conversation_context
        )

        improved_answer2 = apply_improvements(
            "OpenRouter",
            question,
            previous_answer2,
            previous_answer1,
            openrouter_improvements,
            conversation_context
        )

        answer1 = improved_answer1
        answer2 = improved_answer2

        print(
            "\n--- GEMINI — IMPROVED ANSWER ---"
        )

        print(answer1)

        print(
            "\n--- OPENROUTER — IMPROVED ANSWER ---"
        )

        print(answer2)

    # ========================================================
    # STEP 3 — TEAM DRAFT
    # ========================================================

    print("\n" + "=" * 60)
    print("STEP 3 — TEAM DRAFT")
    print("=" * 60)

    team_draft = create_team_draft(
        question,
        answer1,
        answer2,
        conversation_context
    )

    print("\n--- SHARED TEAM DRAFT ---")
    print(team_draft)

    # ========================================================
    # STEP 4 — MUTUAL REVIEW
    # ========================================================

    approved = False

    for approval_round in range(
        1,
        MAX_APPROVAL_ROUNDS + 1
    ):

        print("\n" + "=" * 60)
        print(
            f"STEP 4 — TEAM DRAFT REVIEW {approval_round}"
        )
        print("=" * 60)

        # BOTH agents receive EXACTLY the same draft.

        gemini_review = review_team_draft(
            "Gemini",
            question,
            team_draft,
            conversation_context
        )

        openrouter_review = review_team_draft(
            "OpenRouter",
            question,
            team_draft,
            conversation_context
        )

        print(
            "\n--- GEMINI — AGGRESSIVE REVIEW ---"
        )

        print(gemini_review)

        print(
            "\n--- OPENROUTER — AGGRESSIVE REVIEW ---"
        )

        print(openrouter_review)

        # ----------------------------------------------------
        # IMPORTANT FIX:
        #
        # Prevent NoneType.strip() crash.
        # ----------------------------------------------------

        gemini_review = (
            gemini_review
            or
            "REVISE:\nNo review was returned."
        )

        openrouter_review = (
            openrouter_review
            or
            "REVISE:\nNo review was returned."
        )

        gemini_approved = (
            gemini_review.strip().upper()
            == "APPROVED"
        )

        openrouter_approved = (
            openrouter_review.strip().upper()
            == "APPROVED"
        )

        # ----------------------------------------------------
        # BOTH APPROVE
        # ----------------------------------------------------

        if gemini_approved and openrouter_approved:

            print("\n" + "=" * 60)

            print(
                "BOTH AGENTS APPROVED THE SAME TEAM DRAFT"
            )

            print("=" * 60)

            approved = True

            break

        # ----------------------------------------------------
        # REVISION REQUIRED
        # ----------------------------------------------------

        print("\nREVISION REQUIRED.")

        if approval_round % 2 == 1:
            revision_agent = "Gemini"
        else:
            revision_agent = "OpenRouter"

        print(
            f"Revision performed by: {revision_agent}"
        )

        team_draft = revise_team_draft(
            question,
            team_draft,
            gemini_review,
            openrouter_review,
            revision_agent,
            conversation_context
        )

        print("\n--- REVISED TEAM DRAFT ---")
        print(team_draft)

    # ========================================================
    # STEP 5 — FINAL ANSWER
    # ========================================================

    print("\n" + "=" * 60)
    print("FINAL ANSWER")
    print("=" * 60)

    if approved:

        # IMPORTANT:
        # No additional AI rewriting happens here.
        # The exact mutually approved draft is shown.

        print("\n" + team_draft)

    else:

        print(
            "\nThe team did not reach mutual approval within "
            "the maximum review rounds."
        )

        print("\nLatest team draft:")
        print(team_draft)

    return team_draft


# ============================================================
# MAIN — AI TEAM CHATBOT
# ============================================================

def main():

    print("\n" + "=" * 60)
    print("             QUALITY AI TEAM CHATBOT")
    print("=" * 60)

    print(
        "\nTwo AI agents will collaborate on every question."
    )

    print(
        "Type 'exit', 'quit', or 'bye' to leave."
    )

    conversation_history = []

    while True:

        print("\n" + "-" * 60)

        question = input("\nYou: ").strip()

        # ----------------------------------------------------
        # EXIT
        # ----------------------------------------------------

        if question.lower() in {
            "exit",
            "quit",
            "bye"
        }:

            print("\n" + "=" * 60)
            print("             EXITING AI TEAM")
            print("=" * 60)

            break

        # ----------------------------------------------------
        # EMPTY INPUT
        # ----------------------------------------------------

        if not question:

            print(
                "\nPlease enter a question."
            )

            continue

        # ----------------------------------------------------
        # PROCESS QUESTION
        # ----------------------------------------------------

        try:

            final_answer = answer_question(
                question,
                conversation_history
            )

        except RuntimeError as error:

            print("\n" + "=" * 60)
            print("AI TEAM TEMPORARILY UNAVAILABLE")
            print("=" * 60)

            print(f"\n{error}")

            print(
                "\nYou can try your question again."
            )

            continue

        except Exception as error:

            print("\n" + "=" * 60)
            print("UNEXPECTED ERROR")
            print("=" * 60)

            print(
                f"\n{error}"
            )

            print(
                "\nThe chatbot is still running."
            )

            continue

        # ----------------------------------------------------
        # SAVE CONVERSATION
        # ----------------------------------------------------

        conversation_history.append(
            {
                "user": question,
                "assistant": final_answer
            }
        )

        # ----------------------------------------------------
        # LIMIT CONTEXT
        # ----------------------------------------------------

        if len(conversation_history) > MAX_CONTEXT_TURNS:

            conversation_history = (
                conversation_history[-MAX_CONTEXT_TURNS:]
            )


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":
    main()