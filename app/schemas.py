"""Request and response models (pydantic). *Base/*Create = request body, *Update = PATCH body (all optional), *Out = response."""

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
    """Animal species."""
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
    """Animal sex."""
    male = "male"
    female = "female"


class AnimalStatus(str, Enum):
    """Animal status; active/sick/quarantine count as on the farm."""
    active = "active"
    sick = "sick"
    quarantine = "quarantine"
    sold = "sold"
    deceased = "deceased"


ON_FARM_STATUSES = {AnimalStatus.active.value, AnimalStatus.sick.value, AnimalStatus.quarantine.value}


class Origin(str, Enum):
    """How the animal arrived on the farm."""
    born_on_farm = "born_on_farm"
    purchased = "purchased"
    other = "other"


class PregnancyStatus(str, Enum):
    """State of a breeding's pregnancy."""
    pending = "pending"  # mated, not yet confirmed
    confirmed = "confirmed"
    not_pregnant = "not_pregnant"
    delivered = "delivered"
    aborted = "aborted"


class MatingMethod(str, Enum):
    """Natural mating or artificial insemination."""
    natural = "natural"
    artificial_insemination = "artificial_insemination"


class Product(str, Enum):
    """Production product type."""
    milk = "milk"
    eggs = "eggs"
    wool = "wool"
    meat = "meat"
    other = "other"


DEFAULT_UNIT = {"milk": "liters", "eggs": "count", "wool": "kg", "meat": "kg", "other": "units"}


class TransactionType(str, Enum):
    """Income or expense."""
    income = "income"
    expense = "expense"


# ------------------------------------------------------------------ common bases
class Record(BaseModel):
    """Base of all responses: id and timestamps; unknown stored fields are ignored."""
    model_config = ConfigDict(extra="ignore")

    id: str
    created_at: str | None = None
    updated_at: str | None = None


class Strict(BaseModel):
    """Base of all request bodies: unknown fields are rejected (422), strings are trimmed."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------- farm
class FarmUpdate(Strict):
    """PATCH /v1/farm body. Currency is upper-cased."""
    name: str | None = Field(default=None, min_length=1, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    country: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=200)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class FarmOut(Record):
    """Farm as returned by the API. ``invite_code`` is only filled for managers and the owner;
    ``role`` is the caller's role on this farm."""
    name: str
    currency: str = "USD"
    country: str | None = None
    address: str | None = None
    owner_uid: str | None = None
    invite_code: str | None = None
    role: str | None = None


class FarmCreate(Strict):
    """POST /v1/farms body: create a farm and become its owner."""
    name: str = Field(min_length=2, max_length=80)
    address: str = Field(min_length=5, max_length=200)
    country: str | None = Field(default=None, max_length=60)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class JoinIn(Strict):
    """POST /v1/farms/join body: the farm's invite code, e.g. "GVF-7K3P" (case and dash optional)."""
    invite_code: str = Field(min_length=4, max_length=20)


class MeFarm(BaseModel):
    """The farm summary inside GET /v1/me."""
    id: str
    name: str | None = None


class MeOut(BaseModel):
    """Response of GET /v1/me and of the onboarding calls: where the signed-in user stands."""
    uid: str
    email: str | None = None
    status: str  # none | pending | active | rejected
    role: str | None = None  # owner | manager | worker | viewer, only when status is active
    farm: MeFarm | None = None
    email_verified: bool = False  # false until the 6-digit email code is confirmed (POST /v1/me/verification/verify)


class VerifyIn(Strict):
    """POST /v1/me/verification/verify body: the 6-digit code from the email (spaces are ignored)."""
    code: str = Field(min_length=1, max_length=20)


class VerificationSentOut(BaseModel):
    """Response of POST /v1/me/verification/send."""
    sent_to: str
    resend_after_seconds: int
    expires_in_seconds: int


AssignableRole = Annotated[str, Field(pattern="^(manager|worker|viewer)$")]


class ApproveIn(Strict):
    """POST /v1/farm/members/<uid>/approve body (optional): the role to give, default worker."""
    role: AssignableRole = "worker"


class RoleIn(Strict):
    """PATCH /v1/farm/members/<uid> body."""
    role: AssignableRole


class TransferIn(Strict):
    """POST /v1/farm/transfer-ownership body: the uid of the active member who becomes owner."""
    uid: str = Field(min_length=1, max_length=128)


class MemberOut(BaseModel):
    """A member or a pending request, as listed in GET /v1/farm/members."""
    model_config = ConfigDict(extra="ignore")

    uid: str
    email: str | None = None
    name: str | None = None
    role: str
    status: str  # pending | active
    requested_at: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None


class InviteCodeOut(BaseModel):
    """Response of POST /v1/farm/invite-code."""
    invite_code: str


# ------------------------------------------------------------------- animals
class AnimalBase(Strict):
    """Animal fields a client may send. date_of_birth cannot be in the future."""
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
    """POST /v1/animals body (adds status and photo_url)."""
    status: AnimalStatus = AnimalStatus.active
    photo_url: str | None = None


AnimalUpdate = make_partial(AnimalBase, "AnimalUpdate")


class AnimalOut(Record):
    """Animal as returned, with computed age fields."""
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
    """POST /v1/animals/<id>/status body."""
    status: AnimalStatus
    date: Date = Field(default_factory=today)
    sale_price: float | None = Field(default=None, ge=0, le=1e12)
    buyer: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


class FamilyOut(BaseModel):
    """Response of GET /v1/animals/<id>/family."""
    animal: AnimalOut
    mother: AnimalOut | None = None
    father: AnimalOut | None = None
    siblings: list[AnimalOut] = []
    offspring: list[AnimalOut] = []


# ------------------------------------------------------------------- health
class VaccinationBase(Strict):
    """Vaccination body; next_due_date cannot be before date_given."""
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
    """Vaccination as returned."""
    pass


class TreatmentBase(Strict):
    """Treatment body."""
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
    """Treatment as returned."""
    pass


class VetVisitBase(Strict):
    """Vet visit body."""
    animal_id: str
    visit_date: Date
    vet_name: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=200)
    diagnosis: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    follow_up_date: Date | None = None


VetVisitUpdate = make_partial(VetVisitBase, "VetVisitUpdate")


class VetVisitOut(VetVisitBase, Record):
    """Vet visit as returned."""
    pass


class IllnessBase(Strict):
    """Illness body."""
    animal_id: str
    condition: str = Field(min_length=1, max_length=200)
    start_date: Date
    recovery_date: Date | None = None
    symptoms: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=1000)


IllnessUpdate = make_partial(IllnessBase, "IllnessUpdate")


class IllnessOut(IllnessBase, Record):
    """Illness as returned, with status ongoing/recovered."""
    status: str = "ongoing"  # ongoing | recovered (derived from recovery_date)


class ReminderOut(Record):
    """Reminder as returned, with days_until."""
    source_type: str  # vaccination | vet_visit | birth | custom
    source_id: str | None = None
    animal_id: str | None = None
    title: str
    due_date: Date
    status: str = "pending"  # pending | done
    days_until: int | None = None


class ReminderCreate(Strict):
    """POST /v1/reminders body."""
    title: str = Field(min_length=1, max_length=200)
    due_date: Date
    animal_id: str | None = None


# ----------------------------------------------------------------- breeding
class BreedingBase(Strict):
    """Breeding (mating) body."""
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
    """Breeding as returned, with birth result."""
    actual_birth_date: Date | None = None
    offspring_ids: list[str] = []


class OffspringIn(Strict):
    """One newborn in a birth request."""
    ear_tag: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=80)
    sex: Sex
    birth_weight_kg: float | None = Field(default=None, gt=0, lt=5000)
    stillborn: bool = False


class BirthRequest(Strict):
    """POST /v1/breedings/<id>/births body."""
    birth_date: Date
    offspring: list[OffspringIn] = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)


class BirthOut(BaseModel):
    """Response of a recorded birth: updated breeding and created animals."""
    breeding: BreedingOut
    offspring: list[AnimalOut]


# ------------------------------------------------------ growth & production
class WeightBase(Strict):
    """Weight record body."""
    animal_id: str
    date: Date
    weight_kg: float = Field(gt=0, lt=5000)
    notes: str | None = Field(default=None, max_length=500)


WeightUpdate = make_partial(WeightBase, "WeightUpdate")


class WeightOut(WeightBase, Record):
    """Weight record as returned."""
    pass


class ProductionBase(Strict):
    """Production record body; unit defaults from the product."""
    animal_id: str | None = None  # omit for herd/flock level records
    date: Date
    product: Product
    quantity: float = Field(ge=0, le=1e9)
    unit: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _default_unit(self) -> "ProductionBase":
        if not self.unit:
            self.unit = DEFAULT_UNIT[self.product.value]
        return self


ProductionUpdate = make_partial(ProductionBase, "ProductionUpdate")


class ProductionOut(ProductionBase, Record):
    """Production record as returned."""
    pass


class FeedingBase(Strict):
    """Feeding record body (one animal or a group)."""
    animal_id: str | None = None
    group_name: str | None = Field(default=None, max_length=80)
    date: Date
    feed_type: str = Field(min_length=1, max_length=120)
    quantity_kg: float = Field(gt=0, le=1e7)
    notes: str | None = Field(default=None, max_length=500)


FeedingUpdate = make_partial(FeedingBase, "FeedingUpdate")


class FeedingOut(FeedingBase, Record):
    """Feeding record as returned."""
    pass


class GrowthPoint(BaseModel):
    """One point of the growth chart."""
    date: Date
    weight_kg: float


class GrowthOut(BaseModel):
    """Response of GET /v1/animals/<id>/growth."""
    animal_id: str
    points: list[GrowthPoint]
    latest_weight_kg: float | None = None
    total_gain_kg: float | None = None
    average_daily_gain_kg: float | None = None


class DailyTotal(BaseModel):
    """Total of one day in the production summary."""
    date: Date
    total: float


class ProductionSummary(BaseModel):
    """Response of GET /v1/production/summary."""
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
    """Income/expense body."""
    type: TransactionType
    category: str = Field(min_length=1, max_length=60)
    amount: float = Field(gt=0, le=1e12)
    date: Date
    description: str | None = Field(default=None, max_length=300)
    animal_id: str | None = None


TransactionUpdate = make_partial(TransactionBase, "TransactionUpdate")


class TransactionOut(TransactionBase, Record):
    """Transaction as returned."""
    pass


class MonthlyFinance(BaseModel):
    """Income and expenses of one month."""
    month: str  # YYYY-MM
    income: float
    expenses: float


class FinanceSummary(BaseModel):
    """Response of GET /v1/finance/summary."""
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
    """In-app notification as returned."""
    title: str
    body: str
    type: str = "info"
    animal_id: str | None = None
    reminder_id: str | None = None
    read: bool = False


class DeviceIn(Strict):
    """POST /v1/devices body (FCM token)."""
    token: str = Field(min_length=10, max_length=4096)
    platform: str = Field(pattern="^(android|ios)$")
    # Language the phone shows the app in; pushes to this phone use it. Default: the request's Accept-Language.
    language: str | None = Field(default=None, pattern="^(ar|fr|en)$")


# ---------------------------------------------------------------- dashboard
class UpcomingItem(BaseModel):
    """One upcoming reminder on the dashboard."""
    reminder_id: str
    animal_id: str | None = None
    animal_label: str | None = None
    title: str
    due_date: Date
    days_until: int


class DashboardOut(BaseModel):
    """Response of GET /v1/dashboard."""
    generated_at: str
    period_days: int
    period_from: Date
    period_to: Date
    animals: dict[str, Any]
    movements: dict[str, int]
    health: dict[str, Any]
    breeding: dict[str, Any]
    finance: dict[str, Any] | None = None  # null for workers and viewers
    unread_notifications: int
