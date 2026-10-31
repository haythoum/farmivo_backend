from __future__ import annotations

from datetime import date as Date
from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from app.utils import today


def make_partial(model: type[BaseModel], name: str) -> type[BaseModel]:
    """Build a model where every field of ``model`` is optional (for PATCH bodies)."""
    fields: dict[str, Any] = {}
    for fname, finfo in model.model_fields.items():
        annotation = Annotated[finfo.annotation, *finfo.metadata] if finfo.metadata else finfo.annotation
        fields[fname] = (Optional[annotation], None)
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)  # type: ignore[call-overload]


# --------------------------------------------------------------------------- enums
class Species(str, Enum):
    cattle = "cattle"
    sheep = "sheep"
    goat = "goat"
    pig = "pig"
    horse = "horse"
    chicken = "chicken"
    duck = "duck"
    rabbit = "rabbit"
    other = "other"


class Sex(str, Enum):
    male = "male"
    female = "female"


class AnimalStatus(str, Enum):
    active = "active"
    sick = "sick"
    quarantine = "quarantine"
    sold = "sold"
    deceased = "deceased"


ON_FARM_STATUSES = {AnimalStatus.active.value, AnimalStatus.sick.value, AnimalStatus.quarantine.value}


class Origin(str, Enum):
    born_on_farm = "born_on_farm"
    purchased = "purchased"
    other = "other"


class PregnancyStatus(str, Enum):
    pending = "pending"  # mated, not yet confirmed
    confirmed = "confirmed"
    not_pregnant = "not_pregnant"
    delivered = "delivered"
    aborted = "aborted"


class MatingMethod(str, Enum):
    natural = "natural"
    artificial_insemination = "artificial_insemination"


class Product(str, Enum):
    milk = "milk"
    eggs = "eggs"
    wool = "wool"
    meat = "meat"
    other = "other"


DEFAULT_UNIT = {"milk": "liters", "eggs": "count", "wool": "kg", "meat": "kg", "other": "units"}


class TransactionType(str, Enum):
    income = "income"
    expense = "expense"


# ------------------------------------------------------------------ common bases
class Record(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    created_at: str | None = None
    updated_at: str | None = None


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------- farm
class FarmUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    country: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=200)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class FarmOut(Record):
    name: str
    currency: str = "USD"
    country: str | None = None
    address: str | None = None
    owner_uid: str | None = None


# ------------------------------------------------------------------- animals
class AnimalBase(Strict):
    ear_tag: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=80)
    species: Species
    breed: str | None = Field(default=None, max_length=80)
    sex: Sex
    date_of_birth: Date | None = None
    date_added: Date = Field(default_factory=today)
    origin: Origin = Origin.purchased
    mother_id: str | None = None
    father_id: str | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("date_of_birth")
    @classmethod
    def _dob_not_future(cls, v: Date | None) -> Date | None:
        if v and v > today():
            raise ValueError("date_of_birth cannot be in the future")
        return v


class AnimalCreate(AnimalBase):
    status: AnimalStatus = AnimalStatus.active
    photo_url: str | None = None


AnimalUpdate = make_partial(AnimalBase, "AnimalUpdate")


class AnimalOut(Record):
    ear_tag: str
    name: str | None = None
    species: Species
    breed: str | None = None
    sex: Sex
    date_of_birth: Date | None = None
    date_added: Date | None = None
    origin: Origin = Origin.purchased
    mother_id: str | None = None
    father_id: str | None = None
    notes: str | None = None
    status: AnimalStatus = AnimalStatus.active
    status_date: Date | None = None
    photo_url: str | None = None
    age_days: int | None = None
    age_months: int | None = None
    age_label: str | None = None


class StatusChange(Strict):
    status: AnimalStatus
    date: Date = Field(default_factory=today)
    sale_price: float | None = Field(default=None, ge=0)
    buyer: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


class FamilyOut(BaseModel):
    animal: AnimalOut
    mother: AnimalOut | None = None
    father: AnimalOut | None = None
    siblings: list[AnimalOut] = []
    offspring: list[AnimalOut] = []


# ------------------------------------------------------------------- health
class VaccinationBase(Strict):
    animal_id: str
    vaccine_name: str = Field(min_length=1, max_length=120)
    date_given: Date
    next_due_date: Date | None = None
    batch_number: str | None = Field(default=None, max_length=60)
    administered_by: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _due_after_given(self) -> "VaccinationBase":
        if self.next_due_date and self.next_due_date < self.date_given:
            raise ValueError("next_due_date cannot be before date_given")
        return self


VaccinationUpdate = make_partial(VaccinationBase, "VaccinationUpdate")


class VaccinationOut(VaccinationBase, Record):
    pass


class TreatmentBase(Strict):
    animal_id: str
    name: str = Field(min_length=1, max_length=120)
    medication: str | None = Field(default=None, max_length=120)
    dosage: str | None = Field(default=None, max_length=120)
    start_date: Date
    end_date: Date | None = None
    withdrawal_end_date: Date | None = None  # milk/meat withdrawal period
    administered_by: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


TreatmentUpdate = make_partial(TreatmentBase, "TreatmentUpdate")


class TreatmentOut(TreatmentBase, Record):
    pass


class VetVisitBase(Strict):
    animal_id: str
    visit_date: Date
    vet_name: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=200)
    diagnosis: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    follow_up_date: Date | None = None


VetVisitUpdate = make_partial(VetVisitBase, "VetVisitUpdate")


class VetVisitOut(VetVisitBase, Record):
    pass


class IllnessBase(Strict):
    animal_id: str
    condition: str = Field(min_length=1, max_length=200)
    start_date: Date
    recovery_date: Date | None = None
    symptoms: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=1000)


IllnessUpdate = make_partial(IllnessBase, "IllnessUpdate")


class IllnessOut(IllnessBase, Record):
    status: str = "ongoing"  # ongoing | recovered (derived from recovery_date)


class ReminderOut(Record):
    source_type: str  # vaccination | vet_visit | birth | custom
    source_id: str | None = None
    animal_id: str | None = None
    title: str
    due_date: Date
    status: str = "pending"  # pending | done
    days_until: int | None = None


class ReminderCreate(Strict):
    title: str = Field(min_length=1, max_length=200)
    due_date: Date
    animal_id: str | None = None


# ----------------------------------------------------------------- breeding
class BreedingBase(Strict):
    dam_id: str
    sire_id: str | None = None
    sire_note: str | None = Field(default=None, max_length=200)  # external sire / semen straw
    mating_date: Date
    method: MatingMethod = MatingMethod.natural
    pregnancy_status: PregnancyStatus = PregnancyStatus.pending
    pregnancy_confirmed_date: Date | None = None
    expected_birth_date: Date | None = None
    notes: str | None = Field(default=None, max_length=1000)


BreedingUpdate = make_partial(BreedingBase, "BreedingUpdate")


class BreedingOut(BreedingBase, Record):
    actual_birth_date: Date | None = None
    offspring_ids: list[str] = []


class OffspringIn(Strict):
    ear_tag: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=80)
    sex: Sex
    birth_weight_kg: float | None = Field(default=None, gt=0)
    stillborn: bool = False


class BirthRequest(Strict):
    birth_date: Date
    offspring: list[OffspringIn] = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)


class BirthOut(BaseModel):
    breeding: BreedingOut
    offspring: list[AnimalOut]


# ------------------------------------------------------ growth & production
class WeightBase(Strict):
    animal_id: str
    date: Date
    weight_kg: float = Field(gt=0, lt=5000)
    notes: str | None = Field(default=None, max_length=500)


WeightUpdate = make_partial(WeightBase, "WeightUpdate")


class WeightOut(WeightBase, Record):
    pass


class ProductionBase(Strict):
    animal_id: str | None = None  # omit for herd/flock level records
    date: Date
    product: Product
    quantity: float = Field(ge=0)
    unit: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _default_unit(self) -> "ProductionBase":
        if not self.unit:
            self.unit = DEFAULT_UNIT[self.product.value]
        return self


ProductionUpdate = make_partial(ProductionBase, "ProductionUpdate")


class ProductionOut(ProductionBase, Record):
    pass


class FeedingBase(Strict):
    animal_id: str | None = None
    group_name: str | None = Field(default=None, max_length=80)
    date: Date
    feed_type: str = Field(min_length=1, max_length=120)
    quantity_kg: float = Field(gt=0)
    notes: str | None = Field(default=None, max_length=500)


FeedingUpdate = make_partial(FeedingBase, "FeedingUpdate")


class FeedingOut(FeedingBase, Record):
    pass


class GrowthPoint(BaseModel):
    date: Date
    weight_kg: float


class GrowthOut(BaseModel):
    animal_id: str
    points: list[GrowthPoint]
    latest_weight_kg: float | None = None
    total_gain_kg: float | None = None
    average_daily_gain_kg: float | None = None


class DailyTotal(BaseModel):
    date: Date
    total: float


class ProductionSummary(BaseModel):
    product: Product
    unit: str
    date_from: Date
    date_to: Date
    total: float
    days_with_records: int
    average_per_record_day: float
    daily: list[DailyTotal]


# ------------------------------------------------------------------ finance
class TransactionBase(Strict):
    type: TransactionType
    category: str = Field(min_length=1, max_length=60)
    amount: float = Field(gt=0)
    date: Date
    description: str | None = Field(default=None, max_length=300)
    animal_id: str | None = None


TransactionUpdate = make_partial(TransactionBase, "TransactionUpdate")


class TransactionOut(TransactionBase, Record):
    pass


class MonthlyFinance(BaseModel):
    month: str  # YYYY-MM
    income: float
    expenses: float


class FinanceSummary(BaseModel):
    date_from: Date
    date_to: Date
    currency: str
    income: float
    expenses: float
    net: float
    income_by_category: dict[str, float]
    expenses_by_category: dict[str, float]
    monthly: list[MonthlyFinance]


# ------------------------------------------------------ notifications/devices
class NotificationOut(Record):
    title: str
    body: str
    type: str = "info"
    animal_id: str | None = None
    reminder_id: str | None = None
    read: bool = False


class DeviceIn(Strict):
    token: str = Field(min_length=10, max_length=4096)
    platform: str = Field(pattern="^(android|ios)$")


# ---------------------------------------------------------------- dashboard
class UpcomingItem(BaseModel):
    reminder_id: str
    animal_id: str | None = None
    animal_label: str | None = None
    title: str
    due_date: Date
    days_until: int


class DashboardOut(BaseModel):
    generated_at: str
    period_days: int
    period_from: Date
    period_to: Date
    animals: dict[str, Any]
    movements: dict[str, int]
    health: dict[str, Any]
    breeding: dict[str, Any]
    finance: dict[str, Any]
    unread_notifications: int
