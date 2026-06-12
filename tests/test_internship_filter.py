from __future__ import annotations

import pytest

from internhunter.core.internship_filter import classify_internship


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineering Intern",
        "Summer 2026 Internship - Backend",
        "Data Science Co-op",
        "Investment Banking Summer Analyst",
        "Marketing Apprentice",
        "Lead Generation Intern",
    ],
)
def test_strong_title_is_internship(title: str) -> None:
    assert classify_internship(title).is_internship is True


@pytest.mark.parametrize(
    "title",
    [
        "Senior Backend Engineer",
        "Staff Software Engineer",
        "Engineering Manager",
        "Principal Data Scientist",
        "Backend Engineer II",
        "Brand Partnerships & Strategy Lead",
    ],
)
def test_senior_titles_not_internship_despite_description(title: str) -> None:
    noisy_desc = "We hire new grads and run a campus co-op recruiting pipeline."
    assert classify_internship(title, noisy_desc).is_internship is False


def test_weak_title_signal_counts_when_not_senior() -> None:
    result = classify_internship("New Grad Software Engineer")
    assert result.is_internship is True
    assert result.kind == "new-grad"


def test_description_only_requires_strong_phrase() -> None:
    weak = classify_internship("Software Engineer", "Mentions co-op casually in passing.")
    assert weak.is_internship is False

    strong = classify_internship(
        "Software Engineer", "This is a paid summer internship program for students."
    )
    assert strong.is_internship is True
