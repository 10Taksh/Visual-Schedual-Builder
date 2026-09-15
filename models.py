import secrets
from datetime import time

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, JSON, String, Table, Time
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    availability: Mapped[dict | str] = mapped_column(JSON, default="Open", nullable=False)
    color: Mapped[str] = mapped_column(String(7), unique=True, default=generate_employee_color, nullable=False)

    positions: Mapped[list["Position"]] = relationship(
        secondary=employee_positions,
        back_populates="employees",
    )
    shifts: Mapped[list["Shift"]] = relationship(
        back_populates="employee",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "employment_type IN ('Full-Time', 'Part-Time')",
            name="ck_employee_employment_type",
        ),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)

    employees: Mapped[list[Employee]] = relationship(
        secondary=employee_positions,
        back_populates="positions",
    )


class StoreSettings(Base):
    __tablename__ = "store_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    operating_hours: Mapped[dict] = mapped_column(JSON, nullable=False)


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
        CheckConstraint(
            "day_of_week IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')",
            name="ck_shift_day_of_week",
        ),
        CheckConstraint("end_time > start_time", name="ck_shift_time_order"),
    )
