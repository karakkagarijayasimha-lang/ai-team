import os
import sys
import time
import requests

from dotenv import load_dotenv
from google import genai
from google.genai import types


# ============================================================
# WINDOWS CONSOLE UTF-8
# ============================================================

try:
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

except Exception:
    pass


# ============================================================
# SETUP
# ============================================================

load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")


if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is missing from .env"
    )


if not OPENROUTER_API_KEY:
    raise RuntimeError(
        "OPENROUTER_API_KEY is missing from .env"
    )


# ============================================================
# GEMINI CLIENT
# ============================================================

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(
        timeout=120_000
    ),
)


# ============================================================
# MODEL CONFIGURATION
# ============================================================

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)


OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free"
)


# ============================================================
# COLLABORATION CONFIGURATION
# ============================================================

# OPTIMIZED:
#
# One improvement round is enough for the normal workflow.
#
# We still have a maximum safety limit rather than allowing
# an unlimited collaboration loop.

MAX_IMPROVEMENT_ROUNDS = 1


# Maximum number of times the final Team Draft can go
# through review/revision.

MAX_APPROVAL_ROUNDS = 2


# Previous conversation turns supplied to the agents.

MAX_CONTEXT_TURNS = 3


# STRICT QUALITY GATE:
#
# If both agents do not approve the final Team Draft,
# the answer is NOT released.

RETURN_BEST_DRAFT_IF_NOT_APPROVED = False


# Provider retry count.

PROVIDER_RETRIES = 4


# HTTP timeout.

REQUEST_TIMEOUT = 120


# OpenRouter endpoint.

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)


# Protocol constants.

NO_IMPROVEMENT = (
    "NO_MEANINGFUL_IMPROVEMENT"
)

APPROVED = "APPROVED"


# ============================================================
# CUSTOM ERRORS
# ============================================================

class AgentUnavailableError(RuntimeError):
    """
    A required AI agent could not provide
    a usable response.
    """
    pass


class InvalidAgentResponseError(RuntimeError):
    """
    An AI agent returned an invalid response
    for the required collaboration protocol.
    """
    pass


# ============================================================
# BASIC HELPERS
# ============================================================

def wait_before_retry(attempt):
    """
    Retry delays:

    Attempt 0 -> 4 seconds
    Attempt 1 -> 8 seconds
    Attempt 2 -> 16 seconds
    Attempt 3 -> 32 seconds
    """

    return 4 * (2 ** attempt)


def clean_text(value):

    if value is None:
        return ""

    return str(value).strip()


# ============================================================
# PROTOCOL NORMALIZATION
# ============================================================

def normalize(text):

    value = clean_text(text)

    value = (
        value
        .replace("*", "")
        .replace("`", "")
        .replace("#", "")
    )

    return (
        value
        .strip()
        .strip(".")
        .strip()
        .upper()
    )


def is_no_improvement(text):

    return normalize(text).startswith(
        NO_IMPROVEMENT
    )


def is_approved(text):

    value = normalize(text)

    return (
        value.startswith(APPROVED)
        and
        "REVISE:" not in value
    )


def has_improvement_format(text):

    value = normalize(text)

    return (
        value.startswith(
            "IMPROVEMENTS:"
        )
        or
        value.startswith(
            NO_IMPROVEMENT
        )
    )


def has_review_format(text):

    value = normalize(text)

    return (
        value.startswith(
            APPROVED
        )
        or
        value.startswith(
            "REVISE:"
        )
    )


# ============================================================
# AGENT 1 - GEMINI
# ============================================================

def ask_gemini(prompt):

    last_error = None

    for attempt in range(PROVIDER_RETRIES):

        try:

            # Use generate_content().
            #
            # This avoids the Chat API path that was
            # repeatedly producing 503 errors during testing.

            response = (
                gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                )
            )

            content = clean_text(
                getattr(
                    response,
                    "text",
                    None
                )
            )

            if content:
                return content

            last_error = (
                "Gemini returned an empty response."
            )

        except Exception as error:

            last_error = str(error)

            error_message = (
                last_error.lower()
            )

            error_code = getattr(
                error,
                "code",
                None
            )

            retryable = (
                error_code in (
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                )
                or
                any(
                    marker in error_message
                    for marker in [
                        "408",
                        "429",
                        "500",
                        "502",
                        "503",
                        "504",
                        "service unavailable",
                        "temporarily unavailable",
                        "unavailable",
                        "overloaded",
                        "high demand",
                        "resource exhausted",
                        "resource_exhausted",
                        "timeout",
                        "timed out",
                        "deadline",
                    ]
                )
            )

            if not retryable:

                raise AgentUnavailableError(
                    f"Gemini request failed: "
                    f"{error}"
                ) from error

        if attempt < PROVIDER_RETRIES - 1:

            wait_time = (
                wait_before_retry(
                    attempt
                )
            )

            print(
                "\n[Gemini] Temporary problem: "
                f"{last_error[:180]}"
            )

            print(
                "[Gemini] Attempt "
                f"{attempt + 1}/{PROVIDER_RETRIES}"
            )

            print(
                "[Gemini] Retrying in "
                f"{wait_time} seconds..."
            )

            time.sleep(wait_time)

    raise AgentUnavailableError(
        "Gemini could not provide a response "
        f"after {PROVIDER_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


# ============================================================
# AGENT 2 - OPENROUTER
# ============================================================

def ask_openrouter(prompt):

    last_error = None

    for attempt in range(PROVIDER_RETRIES):

        try:

            response = requests.post(

                OPENROUTER_URL,

                headers={
                    "Authorization":
                        f"Bearer {OPENROUTER_API_KEY}",

                    "Content-Type":
                        "application/json",
                },

                json={

                    "model":
                        OPENROUTER_MODEL,

                    "temperature":
                        0.1,

                    "messages": [

                        {
                            "role":
                                "system",

                            "content":
                                (
                                    "You are an equal "
                                    "AI teammate. "
                                    "Follow the requested "
                                    "output format exactly. "
                                    "Do not add safety labels, "
                                    "metadata, unrelated "
                                    "headers, or commentary."
                                ),
                        },

                        {
                            "role":
                                "user",

                            "content":
                                prompt,
                        },
                    ],
                },

                timeout=REQUEST_TIMEOUT,
            )

            status = response.status_code

            # ------------------------------------------------
            # RATE LIMIT
            # ------------------------------------------------

            if status == 429:

                last_error = (
                    "HTTP 429 rate limit."
                )

            # ------------------------------------------------
            # SERVER ERRORS
            # ------------------------------------------------

            elif (
                status >= 500
                or
                status == 408
            ):

                last_error = (
                    "OpenRouter server error "
                    f"HTTP {status}."
                )

            # ------------------------------------------------
            # OTHER CLIENT ERRORS
            # ------------------------------------------------

            elif 400 <= status < 500:

                raise AgentUnavailableError(
                    f"OpenRouter HTTP {status}: "
                    f"{response.text[:300]}"
                )

            # ------------------------------------------------
            # SUCCESS
            # ------------------------------------------------

            else:

                data = response.json()

                if (
                    isinstance(data, dict)
                    and
                    data.get("error")
                ):

                    last_error = (
                        "OpenRouter error: "
                        f"{str(data['error'])[:250]}"
                    )

                else:

                    choices = (
                        data.get("choices")
                        or []
                    )

                    if not choices:

                        last_error = (
                            "OpenRouter returned "
                            "no choices."
                        )

                    else:

                        message = (
                            choices[0]
                            .get("message")
                            or {}
                        )

                        content = clean_text(
                            message.get(
                                "content"
                            )
                        )

                        if content:

                            return content

                        last_error = (
                            "OpenRouter returned "
                            "empty content."
                        )

        except AgentUnavailableError:

            raise

        except requests.exceptions.Timeout:

            last_error = (
                "OpenRouter request timed out."
            )

        except requests.exceptions.RequestException as error:

            last_error = (
                "OpenRouter request failed: "
                f"{error}"
            )

        except ValueError:

            last_error = (
                "OpenRouter returned invalid JSON."
            )

        if attempt < PROVIDER_RETRIES - 1:

            wait_time = (
                wait_before_retry(
                    attempt
                )
            )

            print(
                f"\n[OpenRouter] {last_error}"
            )

            print(
                "[OpenRouter] Attempt "
                f"{attempt + 1}/{PROVIDER_RETRIES}"
            )

            print(
                "[OpenRouter] Retrying in "
                f"{wait_time} seconds..."
            )

            time.sleep(wait_time)

    raise AgentUnavailableError(
        "OpenRouter could not provide "
        f"a response after {PROVIDER_RETRIES} "
        f"attempts. Last error: {last_error}"
    )


# ============================================================
# AGENT DISPATCH
# ============================================================

def ask_agent(
    agent_name,
    prompt
):

    if agent_name == "Gemini":

        return ask_gemini(prompt)

    if agent_name == "OpenRouter":

        return ask_openrouter(prompt)

    raise ValueError(
        f"Unknown agent: {agent_name}"
    )


# ============================================================
# STRICT PROTOCOL AGENT
# ============================================================

def ask_protocol_agent(
    agent_name,
    prompt,
    validator,
    label
):

    last_invalid = None

    for attempt in range(
        PROVIDER_RETRIES
    ):

        result = clean_text(
            ask_agent(
                agent_name,
                prompt
            )
        )

        if validator(result):

            return result

        last_invalid = result

        if attempt < (
            PROVIDER_RETRIES - 1
        ):

            print(
                f"\n[{agent_name}] Invalid "
                f"{label} response."
            )

            print(
                f"[{agent_name}] Retrying "
                "the same verification..."
            )

            prompt = (
                prompt
                +
                "\n\nIMPORTANT RETRY:\n"
                +
                (
                    "Your previous response "
                    "did not follow the required "
                    f"{label} protocol.\n"
                )
                +
                (
                    "Return ONLY the required "
                    "format. Do not add "
                    "commentary, metadata, "
                    "safety labels, or headers."
                )
            )

            # Small delay instead of another
            # long provider retry delay.

            time.sleep(1)

    raise InvalidAgentResponseError(
        f"{agent_name} repeatedly returned "
        f"an invalid {label} response. "
        f"Last response: {last_invalid}"
    )


# ============================================================
# CONVERSATION HISTORY
# ============================================================

def format_conversation_history(
    conversation_history
):

    if not conversation_history:

        return "No previous conversation."

    recent_history = (
        conversation_history[
            -MAX_CONTEXT_TURNS:
        ]
    )

    formatted = []

    for item in recent_history:

        formatted.append(
            "USER:\n"
            f"{item['user']}\n\n"
            "AI TEAM:\n"
            f"{item['assistant']}"
        )

    return (
        "\n\n--- PREVIOUS TURN ---\n\n"
        .join(formatted)
    )


# ============================================================
# INDEPENDENT ANSWER PROMPT
# ============================================================

def build_independent_prompt(
    agent_label,
    question,
    conversation_context
):

    return f"""
You are {agent_label}, an equal and independent
member of a two-agent AI team.

CURRENT USER QUESTION:

{question}

RELEVANT PREVIOUS CONVERSATION:

{conversation_context}

Answer the user's current question independently.

Priorities:

- Accuracy
- Relevance
- Completeness
- Clear reasoning
- Natural language
- Appropriate detail
- Quality over quantity

Do not unnecessarily repeat previous answers.

Do not mention the AI team.

Do not mention this instruction.

Return ONLY the answer.
"""


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

CURRENT USER QUESTION:

{question}

PREVIOUS CONVERSATION:

{conversation_context}

YOUR CURRENT ANSWER:

{own_answer}

OTHER AGENT'S CURRENT ANSWER:

{other_answer}

Carefully compare both answers.

Find only genuine improvements that would make
YOUR answer more useful for THIS question.

Check for:

1. Factual errors
2. Missing important information
3. Weak reasoning
4. Contradictions
5. Misleading statements
6. Unclear explanations
7. Poor organization
8. Unnecessary information
9. Repetition
10. Wrong level of detail
11. Important examples or edge cases
12. Whether the answer actually satisfies the user

IMPORTANT:

- Do not invent problems.
- Do not change correct information just because
  you prefer different wording.
- Do not make the answer longer without a reason.
- Do not remove useful information.
- Do not blindly copy the other agent.
- If the other agent is wrong, reject it.
- Preserve correct and useful information.
- Quality is more important than quantity.

Return EXACTLY one of:

IMPROVEMENTS:
1. specific genuine improvement
2. specific genuine improvement

OR:

NO_MEANINGFUL_IMPROVEMENT
"""

    return ask_protocol_agent(
        agent_name,
        prompt,
        has_improvement_format,
        "improvement analysis"
    )


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

    if is_no_improvement(
        improvement_points
    ):

        return current_answer

    prompt = f"""
You are {agent_name}, an equal member of
a two-agent AI team.

CURRENT USER QUESTION:

{question}

PREVIOUS CONVERSATION:

{conversation_context}

YOUR CURRENT ANSWER:

{current_answer}

OTHER AGENT'S ANSWER:

{other_answer}

IDENTIFIED IMPROVEMENTS:

{improvement_points}

Create the improved version of YOUR answer.

Rules:

- Fix genuine factual problems.
- Add important missing information.
- Improve weak reasoning.
- Use useful information from the other agent
  when it is correct.
- Reject incorrect suggestions.
- Preserve correct information.
- Remove unnecessary repetition.
- Do not make it longer without reason.
- Do not remove useful information.
- Keep the answer natural.
- Do not mention the collaboration.
- Do not describe the changes.

Return ONLY the improved answer.
"""

    result = clean_text(
        ask_agent(
            agent_name,
            prompt
        )
    )

    if not result:

        raise AgentUnavailableError(
            f"{agent_name} returned an empty "
            "improved answer."
        )

    return result


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
You are creating ONE shared TEAM DRAFT
from two equal AI teammates.

CURRENT USER QUESTION:

{question}

PREVIOUS CONVERSATION:

{conversation_context}

AGENT 1 ANSWER:

{answer1}

AGENT 2 ANSWER:

{answer2}

Create ONE high-quality final candidate answer.

Do NOT mechanically combine the answers.

Instead:

- Keep the strongest correct information.
- Correct factual errors.
- Resolve contradictions.
- Reject incorrect information.
- Remove duplicates.
- Preserve important details.
- Keep useful examples.
- Remove unnecessary information.
- Match the user's actual intention.
- Use an appropriate level of detail.
- Make the answer natural and clear.

Before including information, ask:

"Does this genuinely help the user?"

If not, leave it out.

Do not mention the agents.
Do not mention collaboration.
Do not mention this process.

Return ONLY the Team Draft.
"""

    # Gemini is the designated Team Draft creator.
    #
    # IMPORTANT:
    # There is NO fallback to OpenRouter.

    result = clean_text(
        ask_agent(
            "Gemini",
            prompt
        )
    )

    if not result:

        raise AgentUnavailableError(
            "Team Draft generation returned "
            "an empty response."
        )

    return result


# ============================================================
# REVIEW TEAM DRAFT
# ============================================================

def review_team_draft(
    agent_name,
    question,
    team_draft,
    conversation_context
):

    prompt = f"""
You are {agent_name}, one of two equal AI teammates.

You are reviewing the EXACT SAME Team Draft
that may be shown to the user.

CURRENT USER QUESTION:

{question}

PREVIOUS CONVERSATION:

{conversation_context}

TEAM DRAFT:

{team_draft}

Check carefully for:

- factual errors
- logical errors
- missing important information
- contradictions
- misleading claims
- unclear explanations
- unnecessary information
- unnecessary repetition
- wrong level of detail
- missing useful examples
- failure to answer the user's actual question

Do NOT request changes merely because
you prefer different wording.

Do NOT request interesting but unnecessary
information.

Only request changes that genuinely improve
the answer.

If there is a genuine problem, return:

REVISE:
1. specific problem and correction
2. specific problem and correction

If there are no meaningful problems, return:

APPROVED

Do not rewrite the Team Draft.
"""

    return ask_protocol_agent(
        agent_name,
        prompt,
        has_review_format,
        "team-draft review"
    )


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
You are {revision_agent}, revising a shared
Team Draft created by two equal AI teammates.

CURRENT USER QUESTION:

{question}

PREVIOUS CONVERSATION:

{conversation_context}

CURRENT TEAM DRAFT:

{current_draft}

GEMINI REVIEW:

{gemini_review}

OPENROUTER REVIEW:

{openrouter_review}

Create the next Team Draft.

Use the reviews as evidence,
but reason for yourself.

Rules:

- Fix genuine problems.
- Reject incorrect review suggestions.
- Preserve correct information.
- Add important missing information.
- Remove unnecessary information.
- Resolve contradictions.
- Improve clarity where needed.
- Do not make it unnecessarily long.
- Do not add unrelated information.
- Do not mention the agents.
- Do not mention the reviews.
- Do not mention the revision process.

Return ONLY the revised Team Draft.
"""

    # Only the designated revision agent revises.
    #
    # NO automatic fallback.

    result = clean_text(
        ask_agent(
            revision_agent,
            prompt
        )
    )

    if not result:

        raise AgentUnavailableError(
            "Team Draft revision returned "
            "an empty response."
        )

    return result


# ============================================================
# ANSWER ONE QUESTION
# ============================================================

def answer_question(
    question,
    conversation_history
):

    conversation_context = (
        format_conversation_history(
            conversation_history
        )
    )

    # ========================================================
    # STEP 1
    # ========================================================

    print(
        "\n" + "=" * 60
    )

    print(
        "STEP 1 - INDEPENDENT THINKING"
    )

    print(
        "=" * 60
    )

    # --------------------------------------------------------
    # GEMINI
    # --------------------------------------------------------

    print(
        "\nWaiting for Gemini..."
    )

    answer1 = ask_gemini(
        build_independent_prompt(
            "Agent 1",
            question,
            conversation_context
        )
    )

    print(
        "\n--- AGENT 1 - GEMINI ---"
    )

    print(answer1)

    # --------------------------------------------------------
    # OPENROUTER
    # --------------------------------------------------------

    print(
        "\nWaiting for OpenRouter..."
    )

    answer2 = ask_openrouter(
        build_independent_prompt(
            "Agent 2",
            question,
            conversation_context
        )
    )

    print(
        "\n--- AGENT 2 - OPENROUTER ---"
    )

    print(answer2)


    # ========================================================
    # STEP 2 - ONE CROSS-VERIFICATION ROUND
    # ========================================================

    for round_number in range(
        1,
        MAX_IMPROVEMENT_ROUNDS + 1
    ):

        print(
            "\n" + "=" * 60
        )

        print(
            f"STEP 2 - CROSS-VERIFICATION "
            f"ROUND {round_number}"
        )

        print(
            "=" * 60
        )

        previous_answer1 = answer1
        previous_answer2 = answer2

        # ----------------------------------------------------
        # GEMINI CHECK
        # ----------------------------------------------------

        print(
            "\nGemini is checking its answer..."
        )

        gemini_improvements = (
            find_improvements(
                "Gemini",
                question,
                previous_answer1,
                previous_answer2,
                conversation_context
            )
        )

        # ----------------------------------------------------
        # OPENROUTER CHECK
        # ----------------------------------------------------

        print(
            "\nOpenRouter is checking its answer..."
        )

        openrouter_improvements = (
            find_improvements(
                "OpenRouter",
                question,
                previous_answer2,
                previous_answer1,
                conversation_context
            )
        )

        print(
            "\n--- GEMINI CROSS-CHECK ---"
        )

        print(
            gemini_improvements
        )

        print(
            "\n--- OPENROUTER CROSS-CHECK ---"
        )

        print(
            openrouter_improvements
        )

        # ----------------------------------------------------
        # BOTH AGREE: NO CHANGE
        # ----------------------------------------------------

        if (
            is_no_improvement(
                gemini_improvements
            )
            and
            is_no_improvement(
                openrouter_improvements
            )
        ):

            print(
                "\nBOTH AGENTS FOUND "
                "NO MEANINGFUL IMPROVEMENT."
            )

            break

        # ----------------------------------------------------
        # GEMINI IMPROVES
        # ----------------------------------------------------

        print(
            "\nGemini is producing "
            "its improved answer..."
        )

        improved_answer1 = (
            apply_improvements(
                "Gemini",
                question,
                previous_answer1,
                previous_answer2,
                gemini_improvements,
                conversation_context
            )
        )

        # ----------------------------------------------------
        # OPENROUTER IMPROVES
        # ----------------------------------------------------

        print(
            "\nOpenRouter is producing "
            "its improved answer..."
        )

        improved_answer2 = (
            apply_improvements(
                "OpenRouter",
                question,
                previous_answer2,
                previous_answer1,
                openrouter_improvements,
                conversation_context
            )
        )

        answer1 = improved_answer1
        answer2 = improved_answer2

        print(
            "\n--- GEMINI - IMPROVED ANSWER ---"
        )

        print(answer1)

        print(
            "\n--- OPENROUTER - IMPROVED ANSWER ---"
        )

        print(answer2)


    # ========================================================
    # STEP 3 - TEAM DRAFT
    # ========================================================

    print(
        "\n" + "=" * 60
    )

    print(
        "STEP 3 - TEAM DRAFT"
    )

    print(
        "=" * 60
    )

    team_draft = create_team_draft(
        question,
        answer1,
        answer2,
        conversation_context
    )

    print(
        "\n--- SHARED TEAM DRAFT ---"
    )

    print(team_draft)


    # ========================================================
    # STEP 4 - MUTUAL APPROVAL
    # ========================================================

    for approval_round in range(
        1,
        MAX_APPROVAL_ROUNDS + 1
    ):

        print(
            "\n" + "=" * 60
        )

        print(
            f"STEP 4 - TEAM DRAFT REVIEW "
            f"{approval_round}"
        )

        print(
            "=" * 60
        )

        # ----------------------------------------------------
        # GEMINI REVIEWS EXACT DRAFT
        # ----------------------------------------------------

        print(
            "\nGemini is reviewing "
            "the exact Team Draft..."
        )

        gemini_review = (
            review_team_draft(
                "Gemini",
                question,
                team_draft,
                conversation_context
            )
        )

        # ----------------------------------------------------
        # OPENROUTER REVIEWS EXACT DRAFT
        # ----------------------------------------------------

        print(
            "\nOpenRouter is reviewing "
            "the exact Team Draft..."
        )

        openrouter_review = (
            review_team_draft(
                "OpenRouter",
                question,
                team_draft,
                conversation_context
            )
        )

        print(
            "\n--- GEMINI - REVIEW ---"
        )

        print(
            gemini_review
        )

        print(
            "\n--- OPENROUTER - REVIEW ---"
        )

        print(
            openrouter_review
        )

        # ====================================================
        # BOTH APPROVE
        # ====================================================

        if (
            is_approved(
                gemini_review
            )
            and
            is_approved(
                openrouter_review
            )
        ):

            print(
                "\n" + "=" * 60
            )

            print(
                "BOTH AGENTS APPROVED "
                "THE SAME TEAM DRAFT"
            )

            print(
                "=" * 60
            )

            # IMPORTANT:
            #
            # Return the EXACT approved Team Draft.
            #
            # NO additional rewriting.

            return team_draft


        # ====================================================
        # REVISION REQUIRED
        # ====================================================

        print(
            "\nREVISION REQUIRED."
        )

        # Alternate revision responsibility.

        if approval_round % 2 == 1:

            revision_agent = "Gemini"

        else:

            revision_agent = "OpenRouter"

        print(
            "Revision performed by: "
            f"{revision_agent}"
        )

        team_draft = revise_team_draft(
            question,
            team_draft,
            gemini_review,
            openrouter_review,
            revision_agent,
            conversation_context
        )

        print(
            "\n--- REVISED TEAM DRAFT ---"
        )

        print(team_draft)


    # ========================================================
    # STRICT QUALITY GATE
    # ========================================================

    print(
        "\n" + "=" * 60
    )

    print(
        "VERIFICATION FAILED"
    )

    print(
        "=" * 60
    )

    raise AgentUnavailableError(
        "The two agents did not mutually approve "
        "the final Team Draft within the maximum "
        "approval rounds. "
        "No unchecked answer was released."
    )


# ============================================================
# ERROR DISPLAY
# ============================================================

def print_error_box(
    title,
    error
):

    print(
        "\n" + "=" * 60
    )

    print(title)

    print(
        "=" * 60
    )

    print(
        f"\n{error}"
    )

    print(
        "\nNo unchecked answer was released."
    )


# ============================================================
# MAIN CHATBOT
# ============================================================

def run_info_mode():

    print(
        "\n" + "=" * 60
    )

    print(
        "             QUALITY AI TEAM CHATBOT"
    )

    print(
        "=" * 60
    )

    print(
        "\nTwo AI agents will collaborate "
        "on every question."
    )

    print(
        "Type 'exit', 'quit', or 'bye' to leave."
    )

    print(
        f"\nGemini model: "
        f"{GEMINI_MODEL}"
    )

    print(
        f"OpenRouter model: "
        f"{OPENROUTER_MODEL}"
    )

    print(
        f"\nImprovement rounds: "
        f"{MAX_IMPROVEMENT_ROUNDS}"
    )

    print(
        f"Approval rounds: "
        f"{MAX_APPROVAL_ROUNDS}"
    )


    conversation_history = []


    # ========================================================
    # CHAT LOOP
    # ========================================================

    while True:

        print(
            "\n" + "-" * 60
        )

        try:

            question = input(
                "\nYou: "
            ).strip()

        except (
            KeyboardInterrupt,
            EOFError
        ):

            print(
                "\n\nExiting AI team."
            )

            break


        # ----------------------------------------------------
        # EXIT
        # ----------------------------------------------------

        if question.lower() in {
            "exit",
            "quit",
            "bye"
        }:

            print(
                "\n" + "=" * 60
            )

            print(
                "             EXITING AI TEAM"
            )

            print(
                "=" * 60
            )

            break


        # ----------------------------------------------------
        # EMPTY QUESTION
        # ----------------------------------------------------

        if not question:

            print(
                "\nPlease enter a question."
            )

            continue


        # ====================================================
        # PROCESS QUESTION
        # ====================================================

        try:

            final_answer = answer_question(
                question,
                conversation_history
            )


        except KeyboardInterrupt:

            print(
                "\n\nQuestion cancelled."
            )

            continue


        except AgentUnavailableError as error:

            print_error_box(
                "VERIFICATION COULD NOT BE COMPLETED",
                error
            )

            print(
                "\nPlease try the question again."
            )

            continue


        except InvalidAgentResponseError as error:

            print_error_box(
                "VERIFICATION RESPONSE WAS INVALID",
                error
            )

            print(
                "\nPlease try the question again."
            )

            continue


        except Exception as error:

            print_error_box(
                "UNEXPECTED ERROR",
                error
            )

            continue


        # ====================================================
        # FINAL ANSWER
        # ====================================================

        print(
            "\n" + "=" * 60
        )

        print(
            "FINAL ANSWER"
        )

        print(
            "=" * 60
        )

        # IMPORTANT:
        #
        # This is EXACTLY the Team Draft that
        # both agents approved.
        #
        # No additional AI rewriting occurs.

        print(
            "\n" + final_answer
        )


        # ====================================================
        # SAVE CONVERSATION
        # ====================================================

        conversation_history.append(
            {
                "user":
                    question,

                "assistant":
                    final_answer
            }
        )


        # Keep only the most recent context.

        if (
            len(conversation_history)
            > MAX_CONTEXT_TURNS
        ):

            conversation_history = (
                conversation_history[
                    -MAX_CONTEXT_TURNS:
                ]
            )


# ============================================================
# PROGRAM START
# ============================================================

if __name__ == "__main__":

    run_info_mode()