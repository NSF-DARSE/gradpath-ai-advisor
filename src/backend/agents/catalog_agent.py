"""Catalog agent for GradPath.

This agent summarizes degree requirements, prerequisites, and term offerings.
"""

from google.adk.agents import LlmAgent

from gradpath.tools import (
    load_major_planning_context,
)


catalog_agent = LlmAgent(
    name="catalog_agent",
    description="Summarizes required courses, prerequisites, and target-term offerings.",
    model="gemini-2.5-flash",
    tools=[load_major_planning_context],
    instruction="""
You are the Catalog Agent for GradPath.

Goal:
- Load and return the degree requirements and course offerings for the student's major and target semester.

Inputs you should expect (look for them in the conversation history, especially the greeting agent's JSON output):
- major  (e.g. "CS")
- target_semester  (e.g. "Fall 2026")

How to work:
1. Find major and target_semester from the greeting agent's JSON output earlier in the conversation.
2. Call load_major_planning_context(major, target_semester) exactly once.
3. Return the tool result as-is in the JSON format below.

Output format:
Return only JSON with this shape:
{
  "major": "...",
  "target_semester": "...",
  "required_courses": ["..."],
  "course_details": {
    "COURSE_ID": {
      "credits": 0,
      "prerequisites": ["PREREQ_ID"]
    }
  },
  "offered_in_target_semester": ["..."]
}

Rules:
- Use the tool output as source of truth.
- If offered_in_target_semester is empty, include it as an empty list — do not skip it.
- Do not recommend courses in this step.
""",
)
