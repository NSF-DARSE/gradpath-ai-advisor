"""Root workflow for GradPath.

ADK looks for `root_agent` in this file.

Two pipelines:
- root_agent: full pipeline for the first message (transcript upload)
- planner_only_agent: slim pipeline for follow-up messages (profile already in session)
"""

from google.adk.agents import ParallelAgent, SequentialAgent

from gradpath.agents import (
    catalog_agent,
    greeting_agent,
    history_agent,
    planner_agent,
    transcript_agent,
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
        greeting_agent,  # Step 1: parse any updated inputs from the message
        planner_agent,   # Step 2: re-plan using injected profile data
    ],
)
