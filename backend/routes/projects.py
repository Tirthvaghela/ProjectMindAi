"""Project browsing, filter metadata and analytics endpoints."""

from __future__ import annotations

import re

from flask import Blueprint, request

from db import client as db
from db.schema import DIFFICULTIES, DOMAINS, public_view
from nlp import generator
from routes.helpers import ApiError, get_int, ok, parse_filters

bp = Blueprint("projects", __name__, url_prefix="/api")


def _mongo_query(filters: dict) -> dict:
    """Translate API filters into a Mongo query document."""
    query: dict = {}
    if "domain" in filters:
        query["domain"] = filters["domain"]
    if "difficulty" in filters:
        query["difficulty"] = filters["difficulty"]
    if "technologies" in filters:
        # Case-insensitive exact match on any requested technology. re.escape
        # matters here: "C++" and "Node.js" contain regex metacharacters that
        # would otherwise silently match the wrong documents.
        query["technologies"] = {
            "$in": [
                re.compile(f"^{re.escape(t)}$", re.IGNORECASE)
                for t in filters["technologies"]
            ]
        }
    if "max_duration_weeks" in filters:
        query["duration_weeks"] = {"$lte": filters["max_duration_weeks"]}
    return query


@bp.get("/projects")
def list_projects():
    """Paginated, filterable browse. Not ranked — use /api/search for that."""
    args = request.args.to_dict()
    filters = parse_filters(args)
    limit = get_int(args, "limit", 20, 1, 100)
    skip = get_int(args, "skip", 0, 0, 10_000)

    query = _mongo_query(filters)
    total = db.projects().count_documents(query)
    cursor = (
        db.projects()
        .find(query, {"_id": 0})
        .sort("title", 1)
        .skip(skip)
        .limit(limit)
    )

    return ok(
        list(cursor),
        total=total,
        limit=limit,
        skip=skip,
        has_more=skip + limit < total,
        filters=filters,
    )


@bp.get("/project/<project_id>")
def get_project(project_id: str):
    doc = db.projects().find_one({"project_id": project_id})
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)
    return ok(public_view(doc))


@bp.get("/project/<project_id>/synopsis")
def project_synopsis(project_id: str):
    """Template-generated first-draft synopsis for one project.

    Deterministic and free to call — no external model, so there is nothing to
    rate-limit and nothing to hallucinate a technology the project doesn't use.
    """
    doc = db.projects().find_one({"project_id": project_id}, {"_id": 0})
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)
    return ok(generator.synopsis_for(doc))


@bp.get("/project/<project_id>/roadmap")
def project_roadmap(project_id: str):
    """Phase-by-phase development roadmap sized to the project's duration_weeks."""
    doc = db.projects().find_one({"project_id": project_id}, {"_id": 0})
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)
    return ok(generator.roadmap_for(doc))


@bp.get("/project/<project_id>/milestones")
def project_milestones(project_id: str):
    """Measurable build milestones, one per roadmap phase — derived directly
    from the same roadmap /project/<id>/roadmap returns, so milestones can
    never disagree with it."""
    doc = db.projects().find_one({"project_id": project_id}, {"_id": 0})
    if doc is None:
        raise ApiError(f"No project with id '{project_id}'.", status=404)
    return ok(generator.milestones_for(doc))


@bp.get("/filters")
def available_filters():
    """Filter options for the UI.

    Domains and difficulties come from the schema (the full allowed set, so the
    dropdown is stable), while technologies are derived from what is actually
    in the database — listing a technology no project uses would produce a
    filter that always returns nothing.
    """
    technologies = sorted(db.projects().distinct("technologies"))
    return ok(
        {
            "domains": list(DOMAINS),
            "difficulties": list(DIFFICULTIES),
            "technologies": technologies,
        }
    )


@bp.get("/analytics")
def analytics():
    """Aggregate counts for the dashboard."""
    projects = db.projects()

    def group_count(field: str) -> list[dict]:
        return list(
            projects.aggregate(
                [
                    {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$project": {"_id": 0, "name": "$_id", "count": 1}},
                ]
            )
        )

    top_technologies = list(
        projects.aggregate(
            [
                {"$unwind": "$technologies"},
                {"$group": {"_id": "$technologies", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 15},
                {"$project": {"_id": 0, "name": "$_id", "count": 1}},
            ]
        )
    )

    trending = list(
        db.history().aggregate(
            [
                {"$group": {"_id": "$query", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10},
                {"$project": {"_id": 0, "query": "$_id", "count": 1}},
            ]
        )
    )

    return ok(
        {
            "total_projects": projects.count_documents({}),
            "total_searches": db.history().count_documents({}),
            "by_domain": group_count("domain"),
            "by_difficulty": group_count("difficulty"),
            "top_technologies": top_technologies,
            "trending_searches": trending,
        }
    )
