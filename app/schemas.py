"""Request and response models (pydantic). *Base/*Create = request body, *Update = PATCH body (all optional), *Out = response."""

from __future__ import annotations

from datetime import date as Date
from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, create_model, field_validator, model_validator

from app.utils import today


def _blank_to_none(v: Any) -> Any:
    """"" or spaces mean "none" (a barn id sent empty by a form = outside, no barn)."""
    return None if isinstance(v, str) and not v.strip() else v


# A barn id; empty means no barn. Kept by make_partial (it copies the Annotated metadata).
BarnRef = Annotated[Optional[str], BeforeValidator(_blank_to_none)]


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
    dog = "dog"
    cat = "cat"
    other = "other"


class Sex(str, Enum):
    """Animal sex."""
    male = "male"
    female = "female"


class AnimalStatus(str, Enum):
    """Animal status; active/sick/quarantine count as on the farm, the others mean the animal left it."""
    active = "active"
    sick = "sick"
    quarantine = "quarantine"
    sold = "sold"
    deceased = "deceased"
    donated = "donated"        # voluntary charity (sadaqa)
    gifted = "gifted"          # given as a gift
    sacrificed = "sacrificed"  # sacrificial animal (udhiya)


ON_FARM_STATUSES = {AnimalStatus.active.value, AnimalStatus.sick.value, AnimalStatus.quarantine.value}
# Statuses where the animal is no longer on the farm: its pending reminders are closed.
LEFT_STATUSES = {"sold", "deceased", "donated", "gifted", "sacrificed"}
# Statuses where the animal is dead: its age stops at the status date.
DEAD_STATUSES = {"deceased", "sacrificed"}


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
    name: str | None = None  # the user's own name (PATCH /v1/me), used in greetings and member lists
    status: str  # none | pending | active | rejected
    role: str | None = None  # owner | manager | worker | viewer, only when status is active
    farm: MeFarm | None = None
    email_verified: bool = False  # false until the 6-digit email code is confirmed (POST /v1/me/verification/verify)
    farms_count: int = 0  # active farms of the user (more than one: the apps show a farm switcher)


class MyFarmOut(BaseModel):
    """One farm of GET /v1/me/farms."""
    id: str
    name: str | None = None
    role: str | None = None
    status: str  # active | pending
    current: bool = False


class SwitchFarmIn(Strict):
    """POST /v1/me/farm body: the farm to work in (an active membership)."""
    farm_id: str = Field(min_length=1, max_length=64)


class NameIn(Strict):
    """Body of PATCH /v1/me: the user's own name."""
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def _trim(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Name must not be empty")
        return v


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
    """Animal fields a client may send. date_of_birth cannot be in the future. An empty ear tag gets the animal's
    farm number (app/animal_codes.py, e.g. 01-0007/26); an official national number can be typed instead."""
    ear_tag: str | None = Field(default=None, max_length=40)
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
    # Age by teeth when the date of birth is unknown (see app/age_classes.py; checked against the species).
    age_class: str | None = Field(default=None, max_length=40)
    # What the animal cost. With an origin other than born on farm it is also booked as an expense.
    purchase_price: float | None = Field(default=None, ge=0, le=1e12)
    barn_id: BarnRef = None  # the barn (GET /v1/barns) the animal lives in

    @model_validator(mode="after")
    def _age_class_fits_species(self) -> "AnimalBase":
        from app.age_classes import keys_for

        if self.age_class and self.age_class not in keys_for(self.species.value):
            raise ValueError(f"age_class '{self.age_class}' does not exist for {self.species.value}")
        return self

    @field_validator("ear_tag")
    @classmethod
    def _blank_tag_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

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
    farm_code: str | None = None  # the farm number the app gave it (= ear_tag unless a national number was typed)
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
    buyer: str | None = None        # sold: who bought it
    sale_price: float | None = None  # sold: the price (also an income transaction)
    recipient: str | None = None    # donated / gifted: who received it
    status_notes: str | None = None
    photo_url: str | None = None
    age_class: str | None = None
    age_class_label: str | None = None  # the age class in the caller's language
    breed_label: str | None = None      # the breed in the caller's language (a typed breed as is)
    purchase_price: float | None = None
    barn_id: str | None = None
    barn_name: str | None = None
    # When the animal left the farm (sold, dead, given ...) it leaves its barn; the barn is remembered for
    # that barn's figures (GET /v1/finance/bilan?barn_id=).
    last_barn_id: str | None = None
    last_barn_name: str | None = None
    age_days: int | None = None
    age_months: int | None = None
    age_label: str | None = None


class StatusChange(Strict):
    """POST /v1/animals/<id>/status body. sale_price and buyer for sold, recipient for donated and gifted."""
    status: AnimalStatus
    date: Date = Field(default_factory=today)
    sale_price: float | None = Field(default=None, ge=0, le=1e12)
    buyer: str | None = Field(default=None, max_length=120)
    recipient: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("date")
    @classmethod
    def _not_future(cls, v: Date) -> Date:
        if v > today():
            raise ValueError("date cannot be in the future")
        return v


# --------------------------------------------------------------------- barns
class BarnBase(Strict):
    """A barn (stable, pen, fold) of the farm. ``species_list``: the species it takes (one, several mixed, or
    empty = any). ``species`` is the single species when there is exactly one (kept for older apps: sending
    only ``species`` means ``species_list = [species]``)."""
    name: str = Field(min_length=1, max_length=60)
    species: Species | None = None
    species_list: list[Species] = Field(default_factory=list, max_length=12)
    capacity: int | None = Field(default=None, ge=1, le=100000)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _species_agree(self) -> "BarnBase":
        if self.species and not self.species_list:
            self.species_list = [self.species]
        self.species_list = list(dict.fromkeys(self.species_list))  # each once, in order
        self.species = self.species_list[0] if len(self.species_list) == 1 else None
        return self


BarnUpdate = make_partial(BarnBase, "BarnUpdate")


class BarnOut(BarnBase, Record):
    """Barn as returned, with the number of animals on the farm in it and what needs attention there."""
    animal_count: int = 0
    sick_count: int = 0  # sick or in quarantine
    pregnant_count: int = 0  # confirmed pregnancies of dams in the barn
    vaccines_due_count: int = 0  # vaccinations overdue or due within 7 days


class MoveAnimalsIn(Strict):
    """POST /v1/animals/move body: animals to put in a barn, or outside (no barn) with barn_id null."""
    animal_ids: list[str] = Field(min_length=1, max_length=500)
    barn_id: BarnRef = None


class PasswordResetIn(Strict):
    """POST /v1/auth/password-reset body: the account's email."""
    email: str = Field(min_length=3, max_length=254)


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
    """One newborn in a birth request (empty ear tag: its farm number)."""
    ear_tag: str | None = Field(default=None, max_length=40)
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
    """Income/expense body. An expense can be for the whole farm, for a barn (``barn_id``) or for animals:
    ``whole_barn`` true = every animal on the farm in the barn on save (the server fills ``animal_ids``), else
    the chosen ``animal_ids`` (``animal_id`` = one animal, kept for older apps). The amount is shared equally
    between those animals: each animal's file shows its share."""
    type: TransactionType
    category: str = Field(min_length=1, max_length=60)
    amount: float = Field(gt=0, le=1e12)
    date: Date
    description: str | None = Field(default=None, max_length=300)
    animal_id: str | None = None
    barn_id: BarnRef = None
    whole_barn: bool = False
    animal_ids: list[str] = Field(default_factory=list, max_length=2000)


TransactionUpdate = make_partial(TransactionBase, "TransactionUpdate")


class TransactionOut(TransactionBase, Record):
    """Transaction as returned: ``label`` is the description in the caller's language (purchases and sales
    booked by the app are written for the language of whoever reads them), ``barn_name`` and ``share`` (amount
    per animal when it is shared between animals)."""
    label: str | None = None
    barn_name: str | None = None
    share: float | None = None


class CostLine(BaseModel):
    """One expense that concerns an animal: its share of it."""
    transaction_id: str
    date: Date
    category: str
    label: str | None = None
    amount: float          # this animal's share
    total_amount: float    # the whole expense
    shared_with: int       # how many animals share it (1 = this animal alone)


class AnimalCostsOut(BaseModel):
    """GET /v1/animals/<id>/costs: what the animal cost, what was spent on it and, once sold, the result."""
    currency: str
    purchase_price: float  # 0 when born on the farm
    purchase_date: Date | None = None
    expenses: list[CostLine]
    expenses_total: float
    health_total: float    # of which vet, medicine and vaccines
    total_cost: float      # purchase + expenses
    direct_total: float = 0  # expenses booked on this animal alone
    shared_total: float = 0  # its share of expenses split between several animals (feed of the barn …)
    break_even: float | None = None  # lowest sale price without a loss (= total cost), while on the farm
    sale_price: float | None = None
    sale_date: Date | None = None
    result: float | None = None  # sale price - total cost once sold; - total cost once dead or given


class SoldAnimal(BaseModel):
    """One sold animal in the balance sheet's sales section."""
    id: str
    ear_tag: str | None = None
    name: str | None = None
    species: str | None = None
    date: Date | None = None
    sale_price: float
    total_cost: float      # purchase + its expenses
    result: float          # sale_price - total_cost


class BilanOut(BaseModel):
    """GET /v1/finance/bilan: the herd's balance sheet (all dates), for the farm or one barn.

    profit = (cash_in + herd_value) - (capital + expenses_total), where capital = what was paid for the animals
    still on the farm or sold, and expenses_total includes the price of animals lost (dead) or given away."""
    currency: str
    barn_id: str | None = None
    # 1. Purchases (capital turned into animals)
    purchases_total: float
    purchases_count: int
    lost_purchases: float  # purchase price of the bought animals that died or were given away
    capital: float         # purchases_total - lost_purchases
    # 2. Expenses
    expenses_by_category: dict[str, float]
    operating_expenses: float
    lost_count: int
    expenses_total: float  # operating_expenses + lost_purchases
    # 3. Sales
    sales_total: float
    sales_count: int
    other_income: float    # milk, wool ... (farm-wide, or booked on the barn)
    cash_in: float         # sales_total + other_income
    # 4. Herd and result
    herd_count: int
    herd_value: float      # purchase price + expenses of the animals still on the farm
    sold: list[SoldAnimal] = []  # newest first (sold animals deleted since are not listed)
    sales_result: float = 0      # sum of the sold animals' gains and losses
    profit: float


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
