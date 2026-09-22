import secrets
from datetime import time

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, JSON, String, Table, Time
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.constants import BREAK_DURATION_MINUTES, BREAK_THRESHOLD_MINUTES, DAYS_OF_WEEK, EMPLOYMENT_TYPES


class Base(DeclarativeBase):
    pass


employee_positions = Table(
    "employee_positions",
    Base.metadata,
    Column("employee_id", ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
    Column("position_id", ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True),
)


def generate_employee_color() -> str:
    return f"#{secrets.token_hex(3).upper()}"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # "Open", or {"Monday": "Unavailable", "Sunday": ["09:00-13:00"]}; see services.availability.
    availability: Mapped[dict | str] = mapped_column(JSON, default="Open", nullable=False)
    # Unique so a color identifies exactly one person on the schedule board.
    color: Mapped[str] = mapped_column(String(7), unique=True, default=generate_employee_color, nullable=False)

    positions: Mapped[list["Position"]] = relationship(
        secondary=employee_positions,
        back_populates="employees",
        order_by="Position.sort_order",
    )
    shifts: Mapped[list["Shift"]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(f"employment_type IN ({_sql_list(EMPLOYMENT_TYPES)})", name="ck_employee_employment_type"),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    # Display name shown in tabs and headings; falls back to ``name`` when empty.
    label: Mapped[str | None] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(7), nullable=False, server_default="#53685D")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    employees: Mapped[list[Employee]] = relationship(
        secondary=employee_positions,
        back_populates="positions",
    )

    @property
    def display_label(self) -> str:
        return self.label or self.name

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-")


class StoreSettings(Base):
    __tablename__ = "store_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    operating_hours: Mapped[dict] = mapped_column(JSON, nullable=False)
    # A shift lasting at least the threshold has the duration deducted as an unpaid break.
    # A threshold or duration of 0 disables the rule.
    break_threshold_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=str(BREAK_THRESHOLD_MINUTES))
    break_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=str(BREAK_DURATION_MINUTES))


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[str] = mapped_column(String(40), nullable=False)
    day_of_week: Mapped[str] = mapped_column(String(9), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_deduction: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="shifts")

    __table_args__ = (
        CheckConstraint(f"day_of_week IN ({_sql_list(DAYS_OF_WEEK)})", name="ck_shift_day_of_week"),
        CheckConstraint("end_time > start_time", name="ck_shift_time_order"),
    )
