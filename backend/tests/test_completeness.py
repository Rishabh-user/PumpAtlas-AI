"""How full a record is, and the column that never held the answer.

`data_completeness_pct` is averaged by the quality dashboard, sorted on by search and
filtered on by `completeness_min`. Nothing computed it: it was NULL on all 77 vendors and
all 84 pump models, so the dashboard reported nothing, the sort was a no-op and the
filter could not match. These pin the arithmetic, and the two traps in the column itself.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import VendorTier
from app.models.pump import Pump, PumpModel
from app.models.vendor import Vendor
from app.services import completeness
from app.services.vocabulary import coerce_for_column


def _vendor(**kwargs) -> Vendor:
    return Vendor(name="Amarinth", **kwargs)


class TestAVendorIsMeasuredOnWhatItHolds:
    def test_an_empty_record_is_zero(self):
        assert completeness.vendor_completeness(_vendor(), contact_count=0) == Decimal("0")

    def test_each_field_is_worth_the_same_slice(self):
        one = completeness.vendor_completeness(
            _vendor(website="https://amarinth.com"), contact_count=0
        )
        assert one == Decimal(str(round(1 / completeness.VENDOR_TRACKED, 4)))

    def test_a_contact_counts_as_a_field(self):
        """A supplier record nobody can telephone is incomplete where it matters most."""
        without = completeness.vendor_completeness(_vendor(), contact_count=0)
        with_one = completeness.vendor_completeness(_vendor(), contact_count=1)
        assert with_one > without

    def test_unclassified_is_not_a_classification(self):
        """Every vendor has a tier; the default is the absence of one."""
        default = completeness.vendor_completeness(
            _vendor(vendor_tier=VendorTier.UNCLASSIFIED), contact_count=0
        )
        classified = completeness.vendor_completeness(
            _vendor(vendor_tier=VendorTier.TIER_1_OEM), contact_count=0
        )
        assert default == Decimal("0")
        assert classified > default

    def test_an_empty_array_is_not_a_value(self):
        """An untouched array column comes back as `[]`, which is not None."""
        assert completeness.vendor_completeness(
            _vendor(product_families=[]), contact_count=0
        ) == Decimal("0")
        assert completeness.is_recorded([]) is False
        assert completeness.is_recorded({}) is False
        assert completeness.is_recorded("  ") is False

    def test_zero_is_a_value_somebody_wrote_down(self):
        assert completeness.is_recorded(0) is True
        assert completeness.is_recorded(False) is True

    def test_gaps_name_what_is_missing(self):
        gaps = completeness.vendor_gaps(
            _vendor(website="https://amarinth.com"), contact_count=0
        )
        assert "website" not in gaps
        assert "hq_country" in gaps
        assert "contacts" in gaps


class TestAModelIsMeasuredOnItsSpecs:
    def test_nothing_recorded_is_zero(self):
        assert completeness.model_completeness(PumpModel(), Pump(), {}) == Decimal("0")

    def test_the_family_counts_towards_its_models(self):
        """Pump type and standard are stated once and are true of every variant."""
        bare = completeness.model_completeness(PumpModel(), Pump(), {})
        with_family = completeness.model_completeness(
            PumpModel(model_code="KGSG 40-250"), Pump(product_family="KGSG"), {}
        )
        assert with_family > bare

    def test_the_tracked_total_is_the_whole_specification(self):
        """The same fields the profile page counts, so the two never disagree."""
        assert completeness.MODEL_TRACKED == (
            completeness.TRACKED_SPEC_FIELDS
            + len(completeness.MODEL_ATTRIBUTE_FIELDS)
            + len(completeness.PUMP_ATTRIBUTE_FIELDS)
        )
        assert completeness.TRACKED_SPEC_FIELDS > 100

    def test_row_bookkeeping_is_not_pump_data(self):
        """A spec row's own confidence is not a fact about the pump."""
        for name in ("confidence_level", "verification_status", "notes"):
            assert name not in completeness.spec_field_names("technical")


class TestTheColumnIsARatioHoweverItIsNamed:
    """`Ratio` is NUMERIC(5, 4) - 0 to 1 - and every column using it is named `_pct`."""

    def test_a_full_record_fits_the_column(self):
        """85% as 85 overflows NUMERIC(5, 4) and aborts the transaction it is in."""
        value = completeness.vendor_completeness(
            _vendor(
                website="w",
                hq_country="GB",
                hq_city="Saxmundham",
                description="d",
                vendor_tier=VendorTier.TIER_1_OEM,
                product_families=["API 610"],
                manufacturing_countries=["GB"],
                annual_revenue_usd=Decimal("1"),
                employee_count=10,
                credit_rating="A",
                total_units_supplied=5,
                on_time_delivery_pct=Decimal("0.98"),
                fpso_offshore_experience=True,
            ),
            contact_count=1,
        )
        assert value == Decimal("1")
        assert value <= 1

    def test_it_is_stored_to_four_decimal_places(self):
        value = completeness.vendor_completeness(
            _vendor(website="https://amarinth.com"), contact_count=0
        )
        assert value.as_tuple().exponent >= -4


class TestANumberTooBigForItsColumnIsNotFlushed:
    """The extraction contract asks for percentages 0-100; the ratio columns hold 0-1.

    A page stating "98% on-time delivery" therefore produced 98 for a column whose
    ceiling is 1. PostgreSQL does not truncate that, it raises mid-flush, which aborts
    the transaction and loses every good field written with it.
    """

    @pytest.mark.parametrize(
        ("given", "expected"),
        [(98, Decimal("0.98")), (100, Decimal("1")), (98.5, Decimal("0.985"))],
    )
    def test_a_percentage_on_a_ratio_column_is_read_as_one(self, given, expected):
        value, error = coerce_for_column(Vendor(), "on_time_delivery_pct", given)
        assert error is None
        assert Decimal(str(value)) == expected

    def test_a_value_that_already_fits_is_left_alone(self):
        """0.98 is 98%; guessing that someone meant 0.98% would corrupt the number."""
        value, error = coerce_for_column(Vendor(), "on_time_delivery_pct", 0.98)
        assert error is None
        assert Decimal(str(value)) == Decimal("0.98")

    def test_nonsense_is_refused_with_a_reason_rather_than_raised(self):
        value, error = coerce_for_column(Vendor(), "on_time_delivery_pct", 4500)
        assert value is None
        assert "does not fit" in error

    def test_an_ordinary_column_is_untouched(self):
        value, error = coerce_for_column(Vendor(), "employee_count", 4500)
        assert error is None
        assert value == 4500


class TestQualifyingASupplierIsAPersonsDecision:
    """`approval_status` was readable everywhere and settable nowhere.

    A badge on the profile, a filter on the vendor list, a column in search - and no
    screen or endpoint wrote it, so every record sat at `pending_qualification` unless
    the extractor had written a supplier's own claim into it. These pin what recording a
    decision now does beyond setting the column.
    """

    def _call(self, monkeypatch, vendor, **payload_kwargs):
        import uuid as _uuid

        from app.api.v1 import vendors as routes
        from app.schemas.entities import QualificationDecision

        applied: dict = {}

        def fake_apply(db, entity, values, context, **kwargs):
            for name, value in values.items():
                setattr(entity, name, value)
            applied["values"] = values
            applied["evidence"] = kwargs.get("evidence")
            applied["origin"] = context.origin
            return {"applied": list(values), "unchanged": [], "refused": {}}

        monkeypatch.setattr(routes.provenance, "apply_fields", fake_apply)
        monkeypatch.setattr(routes.audit, "record_audit", lambda *a, **k: None)
        monkeypatch.setattr(routes.audit, "record_version", lambda *a, **k: None)
        monkeypatch.setattr(routes.audit, "snapshot", lambda obj: {})
        monkeypatch.setattr(routes.indexing, "reindex_vendor", lambda *a, **k: 0)

        class _Db:
            def get(self, _model, _id):
                return vendor

            def commit(self):
                pass

            def refresh(self, _obj):
                pass

        class _Principal:
            user_id = _uuid.uuid4()
            is_platform_admin = True
            tenant_id = None

        result = routes.set_qualification(
            vendor.id, QualificationDecision(**payload_kwargs), _Principal(), _Db()
        )
        return result, applied, _Principal.user_id

    def test_an_approval_records_who_made_it(self, monkeypatch):
        import uuid as _uuid

        vendor = Vendor(id=_uuid.uuid4(), name="Amarinth", tenant_id=None)
        result, _, user_id = self._call(
            monkeypatch,
            vendor,
            approval_status="approved",
            note="Audited 12 Aug; API 610 certificate on file.",
        )
        assert vendor.approved_by_user_id == user_id
        assert result["approval_status"] == "approved"

    def test_the_reason_is_stored_as_the_evidence_for_the_status(self, monkeypatch):
        import uuid as _uuid

        from app.models.enums import ValueOrigin

        vendor = Vendor(id=_uuid.uuid4(), name="Amarinth", tenant_id=None)
        _, applied, _ = self._call(
            monkeypatch,
            vendor,
            approval_status="approved",
            note="Two FPSO references checked with the operator.",
        )
        assert applied["origin"] == ValueOrigin.MANUAL
        assert applied["evidence"]["approval_status"].startswith("Two FPSO")

    def test_withdrawing_an_approval_clears_the_approver_and_the_expiry(self, monkeypatch):
        import uuid as _uuid
        from datetime import date

        vendor = Vendor(
            id=_uuid.uuid4(),
            name="Amarinth",
            tenant_id=None,
            approved_by_user_id=_uuid.uuid4(),
            approval_expiry=date(2027, 1, 1),
        )
        self._call(
            monkeypatch,
            vendor,
            approval_status="suspended",
            note="Sanctions screening outstanding since the ownership change.",
        )
        assert vendor.approved_by_user_id is None
        assert vendor.approval_expiry is None

    def test_a_decision_without_a_reason_is_not_a_decision(self):
        import pydantic

        from app.schemas.entities import QualificationDecision

        with pytest.raises(pydantic.ValidationError):
            QualificationDecision(approval_status="approved", note="ok")
