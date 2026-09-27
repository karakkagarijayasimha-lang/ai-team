import os
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


# ============================================================
# AGENT 1 — GEMINI
# ============================================================

def ask_gemini(prompt):
    response = gemini_client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt
    )

    return response.text.strip()


# ============================================================
# AGENT 2 — OPENROUTER
# ============================================================

def ask_openrouter(prompt):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
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

    response.raise_for_status()

    data = response.json()

    return data["choices"][0]["message"]["content"].strip()


# ============================================================
# FIND IMPROVEMENTS
# ============================================================

def find_improvements(agent_name, question, own_answer, other_answer):

    prompt = f"""
You are {agent_name}, an equal member of a two-agent AI team.

USER QUESTION:
{question}

YOUR CURRENT ANSWER:
{own_answer}

OTHER AGENT'S CURRENT ANSWER:
{other_answer}


Your job in this stage is NOT to simply approve your answer.

Your job is to aggressively search for genuine ways to make your answer
better for the user.

Think deeply about the actual question and the actual answers.

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
11. Better examples that would improve understanding
12. Important edge cases
13. Important assumptions
14. Whether the answer actually satisfies the user's intention
15. Whether something from the other agent's answer is genuinely better
   and should be incorporated

IMPORTANT:

- Do not invent problems just to make a change.
- Do not change correct information merely for stylistic preference.
- Do not make the answer longer without a useful reason.
- Do not make the answer shorter if that removes important information.
- Preserve strong parts of your existing answer.
- If the other agent has useful information, consider incorporating it.
- If the other agent is wrong, do NOT copy it.
- Use your own reasoning to decide what is actually correct.
- Focus on improving QUALITY, not QUANTITY.

Think like a perfectionist teammate:

"What can I genuinely improve in my answer after seeing the other
agent's answer?"

Return ONLY a concise list of the specific improvements that should
be made.

If you find no meaningful improvement, return:

NO_MEANINGFUL_IMPROVEMENT
"""

    if agent_name == "Gemini":
        return ask_gemini(prompt)

    return ask_openrouter(prompt)


# ============================================================
# APPLY IMPROVEMENTS
# ============================================================

def apply_improvements(
    agent_name,
    question,
    current_answer,
    other_answer,
    improvement_points
):

    prompt = f"""
You are {agent_name}, an equal member of a two-agent AI team.

USER QUESTION:
{question}

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
- Do NOT remove useful information just to make it shorter.
- Make the answer clear, natural, accurate and useful.
- Answer the user's actual intention.
- Do not mention this collaboration.
- Do not mention the other agent.
- Do not describe what you changed.

Return ONLY the improved answer.
"""

    if agent_name == "Gemini":
        return ask_gemini(prompt)

    return ask_openrouter(prompt)


# ============================================================
# CREATE TEAM DRAFT
# ============================================================

def create_team_draft(question, answer1, answer2):

    prompt = f"""
You are creating a shared TEAM DRAFT from two equal AI teammates.

USER QUESTION:
{question}

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
- Include useful examples when they genuinely help.
- Keep the answer focused on the user's actual intention.
- Avoid unnecessary verbosity.
- Do not omit important information merely to be concise.
- Make the result natural and easy to understand.
- Do not mention the agents.
- Do not mention collaboration.
- Do not say "Agent 1 says..." or "Agent 2 says..."

The final draft should feel like ONE excellent answer written directly
for the user.

Return ONLY the team draft.
"""

    return ask_gemini(prompt)


# ============================================================
# AGGRESSIVE TEAM DRAFT REVIEW
# ============================================================

def review_team_draft(agent_name, question, team_draft):

    prompt = f"""
You are {agent_name}, one of two equal AI teammates.

The following is the EXACT SAME TEAM DRAFT that the user may receive.

USER QUESTION:
{question}

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
- weak examples
- missing examples where one is genuinely needed
- whether it actually answers the user's intention
- whether any statement should be corrected or qualified

IMPORTANT:

Do not request changes merely because you personally prefer different
wording.

Only identify genuine improvements.

If there are genuine problems, return:

REVISE:
1. ...
2. ...
3. ...

If after serious inspection the draft has no meaningful problems, return
exactly:

APPROVED

Do not rewrite the draft.
"""

    if agent_name == "Gemini":
        return ask_gemini(prompt)

    return ask_openrouter(prompt)


# ============================================================
# REVISE TEAM DRAFT
# ============================================================

def revise_team_draft(
    question,
    current_draft,
    gemini_review,
    openrouter_review,
    revision_agent
):

    prompt = f"""
You are {revision_agent}, revising a shared answer created by two equal
AI teammates.

USER QUESTION:
{question}

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
- Do not make it longer without a reason.
- Do not make it shorter if important information would be lost.
- Do not introduce unrelated information.
- Do not mention the reviews.
- Do not mention the agents.
- Do not describe the revision process.

Return ONLY the revised team draft.
"""

    if revision_agent == "Gemini":
        return ask_gemini(prompt)

    return ask_openrouter(prompt)


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 60)
    print("                 AI TEAM")
    print("=" * 60)

    question = input("\nEnter your question: ").strip()

    if not question:
        print("\nPlease enter a question.")
        return


    # ========================================================
    # STEP 1 — INDEPENDENT ANSWERS
    # ========================================================

    print("\n" + "=" * 60)
    print("STEP 1 — INDEPENDENT THINKING")
    print("=" * 60)

    answer1_prompt = f"""
You are Agent 1, an independent member of an AI team.

Answer this user question:

{question}

Give your best possible answer.

Priorities:

- Accuracy
- Relevance
- Completeness
- Clear reasoning
- Natural language
- Useful structure
- Appropriate detail

Do not mention the AI team.
Do not mention collaboration.

Return ONLY the answer.
"""

    answer2_prompt = f"""
You are Agent 2, an independent member of an AI team.

Answer this user question independently:

{question}

Give your best possible answer.

Priorities:

- Accuracy
- Relevance
- Completeness
- Clear reasoning
- Natural language
- Useful structure
- Appropriate detail

Do not mention the AI team.
Do not mention collaboration.

Return ONLY the answer.
"""

    answer1 = ask_gemini(answer1_prompt)
    answer2 = ask_openrouter(answer2_prompt)

    print("\n--- AGENT 1 — GEMINI ---")
    print(answer1)

    print("\n--- AGENT 2 — OPENROUTER ---")
    print(answer2)


    # ========================================================
    # STEP 2 — ACTIVE IMPROVEMENT LOOP
    # ========================================================

    for round_number in range(1, MAX_IMPROVEMENT_ROUNDS + 1):

        print("\n" + "=" * 60)
        print(f"STEP 2 — IMPROVEMENT ROUND {round_number}")
        print("=" * 60)

        # ----------------------------------------------------
        # Both agents actively search for improvements
        # ----------------------------------------------------

        gemini_improvements = find_improvements(
            "Gemini",
            question,
            answer1,
            answer2
        )

        openrouter_improvements = find_improvements(
            "OpenRouter",
            question,
            answer2,
            answer1
        )

        print("\n--- GEMINI: WHAT CAN I IMPROVE? ---")
        print(gemini_improvements)

        print("\n--- OPENROUTER: WHAT CAN I IMPROVE? ---")
        print(openrouter_improvements)


        # ----------------------------------------------------
        # If both genuinely find nothing, stop.
        #
        # This is NOT the main decision mechanism.
        # Agents are first forced to actively search.
        # ----------------------------------------------------

        if (
            "NO_MEANINGFUL_IMPROVEMENT" in
            gemini_improvements.upper()
            and
            "NO_MEANINGFUL_IMPROVEMENT" in
            openrouter_improvements.upper()
        ):

            print("\nBOTH AGENTS FOUND NO MEANINGFUL IMPROVEMENT.")
            break


        # ----------------------------------------------------
        # Each agent improves its OWN answer.
        # ----------------------------------------------------

        answer1 = apply_improvements(
            "Gemini",
            question,
            answer1,
            answer2,
            gemini_improvements
        )

        answer2 = apply_improvements(
            "OpenRouter",
            question,
            answer2,
            answer1,
            openrouter_improvements
        )

        print("\n--- GEMINI — IMPROVED ANSWER ---")
        print(answer1)

        print("\n--- OPENROUTER — IMPROVED ANSWER ---")
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
        answer2
    )

    print("\n--- SHARED TEAM DRAFT ---")
    print(team_draft)


    # ========================================================
    # STEP 4 — AGGRESSIVE MUTUAL REVIEW
    # ========================================================

    approved = False

    for approval_round in range(1, MAX_APPROVAL_ROUNDS + 1):

        print("\n" + "=" * 60)
        print(f"STEP 4 — TEAM DRAFT REVIEW {approval_round}")
        print("=" * 60)

        # BOTH agents receive the EXACT SAME draft.

        gemini_review = review_team_draft(
            "Gemini",
            question,
            team_draft
        )

        openrouter_review = review_team_draft(
            "OpenRouter",
            question,
            team_draft
        )

        print("\n--- GEMINI — AGGRESSIVE REVIEW ---")
        print(gemini_review)

        print("\n--- OPENROUTER — AGGRESSIVE REVIEW ---")
        print(openrouter_review)


        gemini_approved = (
            gemini_review.strip().upper() == "APPROVED"
        )

        openrouter_approved = (
            openrouter_review.strip().upper() == "APPROVED"
        )


        # ----------------------------------------------------
        # BOTH APPROVE
        # ----------------------------------------------------

        if gemini_approved and openrouter_approved:

            print("\n" + "=" * 60)
            print("BOTH AGENTS APPROVED THE SAME TEAM DRAFT")
            print("=" * 60)

            approved = True
            break


        # ----------------------------------------------------
        # SOMEONE FOUND A REAL PROBLEM
        # ----------------------------------------------------

        print("\nREVISION REQUIRED.")

        # Alternate who performs the actual revision.
        # This keeps the two-agent architecture balanced.

        if approval_round % 2 == 1:
            revision_agent = "Gemini"
        else:
            revision_agent = "OpenRouter"

        print(f"Revision performed by: {revision_agent}")

        team_draft = revise_team_draft(
            question,
            team_draft,
            gemini_review,
            openrouter_review,
            revision_agent
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


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()