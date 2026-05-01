"""Pydantic models for the GradPath UI API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CompletedCourse(BaseModel):
    course_id: str
    title: str
    term: Optional[str] = None
    grade: Optional[str] = None
    credits: int = 0


class ProgressSummary(BaseModel):
    major: str
    target_semester: str
    credits_earned: int
    required_courses_total: int
    required_courses_completed: int
    required_courses_remaining: int
    percent_complete: float
    total_recommended_credits: int = 0


class RecommendedCourse(BaseModel):
    course_id: str
    title: str
    credits: int
    reason: str


class AdvisingNote(BaseModel):
    level: str = Field(description="info, warning, or success")
    title: str
    message: str


class StudentSnapshot(BaseModel):
    student_name: str
    student_id: str
    major: str
    current_semester: str
    source: str
    student_type: Optional[str] = None
    gpa: Optional[float] = None
    expected_graduation: Optional[str] = None
    career_goal: Optional[str] = None
    preferences: Optional[str] = None
    email: Optional[str] = None


class PlannedCourse(BaseModel):
    course_id: str
    title: str
    credits: int


class PlannedSemester(BaseModel):
    term: str
    courses: List[PlannedCourse]
    total_credits: int


class DashboardData(BaseModel):
    student: StudentSnapshot
    completed_courses: List[CompletedCourse]
    progress_summary: ProgressSummary
    recommended_courses: List[RecommendedCourse]
    advising_notes: List[AdvisingNote]
    planned_semesters: List[PlannedSemester] = []


class ChatMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str
    attachment_name: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: ChatMessage
    dashboard: DashboardData
    history: List[ChatMessage]


class SessionBootstrap(BaseModel):
    session_id: str
    dashboard: DashboardData
    history: List[ChatMessage]


class StructuredAgentResponse(BaseModel):
    reply_text: str
    dashboard: Optional[DashboardData] = None  # None means keep the existing dashboard unchanged
    profile: Optional[Dict[str, Any]] = None


class ResponseSchemaExample(BaseModel):
    completed_courses: List[CompletedCourse]
    progress_summary: ProgressSummary
    recommended_courses: List[RecommendedCourse]
    advising_notes: List[AdvisingNote]
