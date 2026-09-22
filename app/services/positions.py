from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import POSITION_SLUG_ALIASES
from app.models import Position


def position_to_dict(position: Position) -> dict:
    return {
        "id": position.id,
        "name": position.name,
        "label": position.display_label,
        "slug": position.slug,
        "color": position.color,
        "sort_order": position.sort_order,
    }


def list_positions(session: Session) -> list[Position]:
    return list(session.scalars(select(Position).order_by(Position.sort_order, Position.name)))


def positions_by_name(session: Session) -> dict[str, Position]:
    return {position.name: position for position in list_positions(session)}


def resolve_position(session: Session, slug: str) -> Position | None:
    """Find the position behind a URL slug such as ``cashier`` or an alias like ``supervisor``."""
    slug = slug.lower()
    if slug in POSITION_SLUG_ALIASES:
        return session.scalar(select(Position).where(Position.name == POSITION_SLUG_ALIASES[slug]))
    return next((position for position in list_positions(session) if position.slug == slug), None)
