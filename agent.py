"""Root workflow for GradPath.

ADK looks for `root_agent` in this file.

Two pipelines:
- root_agent: full pipeline for the first message (transcript upload)
- planner_only_agent: slim pipeline for follow-up messages (profile already in session)
"""

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from gradpath.agents import (
    catalog_agent,
    greeting_agent,
    history_agent,
    planner_agent,
    transcript_agent,
)
from gradpath.agents.greeting_agent import STANDALONE_GREETING_INSTRUCTION
from gradpath.agents.guardrails import check_input

# ADK does not allow the same agent instance to have two parent agents.
# We need separate instances of greeting_agent and planner_agent for the slim pipeline.

# Standalone conversational agent — used before any profile exists (e.g. "hi")
standalone_greeting_agent = LlmAgent(
    name="standalone_greeting_agent",
    description="Conversational advisor that collects student info through natural dialogue.",
    model="gemini-2.5-flash",
    instruction=STANDALONE_GREETING_INSTRUCTION,
    before_agent_callback=check_input,
)

_followup_greeting_agent = LlmAgent(
    name="followup_greeting_agent",
    description="Collects only changed planning inputs on follow-up messages.",
    model="gemini-2.5-flash",
    instruction=greeting_agent.instruction,
    before_agent_callback=check_input,
)

# Standalone intent detector — runs just the greeting agent to classify intent and answer questions
followup_intent_agent = LlmAgent(
    name="followup_intent_agent",
    description="Detects intent (plan_change / question / chat) and answers questions conversationally.",
    model="gemini-2.5-flash",
    instruction=greeting_agent.instruction,
    before_agent_callback=check_input,
)

_followup_planner_agent = LlmAgent(
    name="followup_planner_agent",
    description="Recommends next-semester courses for follow-up messages.",
    model="gemini-2.5-flash",
    tools=planner_agent.tools,
    instruction=planner_agent.instruction,
)

# transcript + catalog are independent — run them at the same time
_parallel_middle = ParallelAgent(
    name="gradpath_parallel_middle",
    description="Parses transcript and loads catalog requirements simultaneously.",
    sub_agents=[transcript_agent, catalog_agent],
)

# Full pipeline — used on the first message when no profile exists yet
root_agent = SequentialAgent(
    name="gradpath_root_agent",
    description="Runs the full GradPath academic planning flow for new sessions.",
    sub_agents=[
        greeting_agent,     # Step 1: collect student planning inputs
        _parallel_middle,   # Step 2: parse transcript + load catalog in parallel
        history_agent,      # Step 3: summarize completed courses from transcript
        planner_agent,      # Step 4: recommend next-semester courses
    ],
)

# Slim pipeline — used on follow-up messages when profile is already in session
planner_only_agent = SequentialAgent(
    name="gradpath_planner_only_agent",
    description="Runs greeting + planner only for follow-up messages.",
    sub_agents=[
        _followup_greeting_agent,  # Step 1: parse any updated inputs from the message
        _followup_planner_agent,   # Step 2: re-plan using injected profile data
    ],
)
