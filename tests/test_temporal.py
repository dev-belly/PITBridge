from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import random
import unittest

from pitbridge.core import Decision, FeatureSpec, Observation, build_snapshot, reference_snapshot
from pitbridge.demo import demo_inputs
from pitbridge.bundle import decode_inputs


def observation(**changes):
    fields = dict(record_id="r1", entity_id="A", source="tax", feature="revenue", event_at="2026-01-01T00:00:00Z", published_at="2026-01-02T00:00:00Z", ingested_at="2026-01-03T00:00:00Z", revision=1, value=10.0)
    fields.update(changes)
    return Observation(**fields)


def snapshot(records, at="2026-01-05T00:00:00Z", age=None, entity="A"):
    return build_snapshot(records, [Decision("D", entity, at)], [FeatureSpec("tax", "revenue", age)])[0]


class TemporalTests(unittest.TestCase):
    def test_historical_revision_cannot_change_old_decision(self):
        revision = observation(record_id="r2", revision=2, value=90, published_at="2026-01-10T00:00:00Z", ingested_at="2026-01-10T00:00:00Z")
        self.assertEqual(snapshot([observation(), revision]).value, 10)
        self.assertEqual(snapshot([observation(), revision], "2026-01-10T00:00:00Z").value, 90)

    def test_ingestion_delay_is_not_publication_time(self):
        row = snapshot([observation(ingested_at="2026-01-08T00:00:00Z")])
        self.assertEqual(row.status, "not_available")
        self.assertIsNone(row.value)

    def test_embargo_requires_publication_even_if_ingested(self):
        self.assertEqual(snapshot([observation(published_at="2026-01-08T00:00:00Z")]).status, "not_available")

    def test_equality_at_decision_is_inclusive(self):
        row = snapshot([observation()], "2026-01-03T00:00:00Z")
        self.assertEqual(row.record_id, "r1")

    def test_microsecond_after_decision_is_excluded(self):
        self.assertEqual(snapshot([observation()], "2026-01-02T23:59:59.999999Z").status, "not_available")

    def test_future_event_is_never_selected(self):
        self.assertEqual(snapshot([observation()], "2025-12-31T00:00:00Z").status, "no_history")

    def test_max_age_boundary_includes_exact_cutoff(self):
        self.assertEqual(snapshot([observation()], age=4).status, "selected")
        self.assertEqual(snapshot([observation()], "2026-01-05T00:00:00.000001Z", age=4).status, "stale")

    def test_zero_max_age_requires_same_instant(self):
        row = observation(published_at="2026-01-01T00:00:00Z", ingested_at="2026-01-01T00:00:00Z")
        self.assertEqual(snapshot([row], "2026-01-01T00:00:00Z", age=0).status, "selected")
        self.assertEqual(snapshot([row], "2026-01-01T00:00:00.000001Z", age=0).status, "stale")

    def test_known_tombstone_does_not_resurrect_old_revision(self):
        tombstone = observation(record_id="del", revision=2, value=None, deleted=True)
        self.assertEqual(snapshot([observation(), tombstone]).status, "deleted")

    def test_future_tombstone_does_not_erase_history(self):
        tombstone = observation(record_id="del", revision=2, value=None, deleted=True, ingested_at="2026-01-09T00:00:00Z")
        self.assertEqual(snapshot([observation(), tombstone]).value, 10)

    def test_tombstone_is_scoped_to_one_event(self):
        recent = observation(record_id="recent", event_at="2026-01-02T00:00:00Z", value=30)
        tombstone = replace(recent, record_id="del", revision=2, deleted=True, value=None)
        self.assertEqual(snapshot([observation(), recent, tombstone]).record_id, "r1")

    def test_late_lower_revision_does_not_replace_higher_revision(self):
        old = observation(ingested_at="2026-01-04T00:00:00Z")
        newer = observation(record_id="r2", revision=2, value=20)
        self.assertEqual(snapshot([old, newer]).value, 20)

    def test_event_order_precedes_revision_number(self):
        old = observation(revision=99)
        recent = observation(record_id="recent", event_at="2026-01-02T00:00:00Z", value=40)
        self.assertEqual(snapshot([old, recent]).value, 40)

    def test_timezones_are_compared_as_utc_instants(self):
        row = observation(ingested_at="2026-01-03T08:00:00+08:00")
        self.assertEqual(snapshot([row], "2026-01-02T19:00:00-05:00").status, "selected")

    def test_entity_isolation_and_missing_rows_are_preserved(self):
        self.assertEqual(snapshot([observation()], entity="B").status, "no_history")
        rows = build_snapshot([], [Decision("D", "A", "2026-01-05T00:00:00Z")], [FeatureSpec("tax", "revenue"), FeatureSpec("bank", "cash")])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.value is None for r in rows))

    def test_sources_with_same_feature_name_are_isolated(self):
        obs = [observation(), observation(record_id="bank", source="bank", value=123)]
        rows = build_snapshot(obs, [Decision("D", "A", "2026-01-05T00:00:00Z")], [FeatureSpec("tax", "revenue"), FeatureSpec("bank", "revenue")])
        self.assertEqual({r.source:r.value for r in rows}, {"bank":123, "tax":10})

    def test_shuffle_does_not_change_snapshot(self):
        obs, dec, specs = decode_inputs(demo_inputs())
        expected = build_snapshot(obs, dec, specs)
        rng = random.Random(42)
        for _ in range(10):
            rng.shuffle(obs); rng.shuffle(dec); rng.shuffle(specs)
            self.assertEqual(build_snapshot(obs,dec,specs), expected)

    def test_appending_future_revisions_cannot_change_old_rows(self):
        obs, dec, specs = decode_inputs(demo_inputs())
        extra = replace(obs[0], record_id="future", revision=1000, value=None, deleted=True, published_at="2027-01-01T00:00:00Z", ingested_at="2027-01-01T00:00:00Z")
        self.assertEqual(build_snapshot(obs,dec,specs), build_snapshot(obs+[extra],dec,specs))

    def test_randomized_sql_matches_independent_enumeration(self):
        rng = random.Random(711)
        origin = datetime(2026,1,1,tzinfo=timezone.utc)
        def stamp(day):
            return (origin+timedelta(days=day)).isoformat()
        for trial in range(40):
            obs = []
            for entity in ("A","B"):
                for source in ("tax","bank"):
                    for event in range(4):
                        for revision in range(1,4):
                            deleted = rng.random() < .2
                            obs.append(Observation(f"{trial}-{entity}-{source}-{event}-{revision}",entity,source,"value",stamp(event*3),stamp(event*3+rng.randrange(8)),stamp(event*3+rng.randrange(12)),revision,None if deleted else rng.uniform(-100,100),deleted))
            dec = [Decision(f"D{i}",rng.choice(("A","B","C")),stamp(rng.randrange(20))) for i in range(12)]
            specs = [FeatureSpec("tax","value",rng.choice((None,0,5,20))),FeatureSpec("bank","value",5)]
            self.assertEqual(build_snapshot(obs,dec,specs),reference_snapshot(obs,dec,specs))


class ContractTests(unittest.TestCase):
    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            snapshot([observation(), observation()])

    def test_duplicate_logical_revisions_are_rejected(self):
        with self.assertRaises(ValueError):
            snapshot([observation(), observation(record_id="other")])

    def test_duplicate_decisions_and_specs_are_rejected(self):
        d = Decision("D","A","2026-01-05T00:00:00Z")
        s = FeatureSpec("tax","revenue")
        for dec,spec in (([d,d],[s]),([d],[s,s])):
            with self.subTest(decisions=len(dec),specs=len(spec)), self.assertRaises(ValueError):
                build_snapshot([observation()],dec,spec)

    def test_invalid_values_and_revisions_are_rejected(self):
        for value in (float("nan"),float("inf"),None,True,"10"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                observation(value=value)
        for revision in (0,-1,1.5,True,2**63):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                observation(revision=revision)

    def test_tombstone_requires_boolean_and_null_value(self):
        for fields in ({"deleted":1},{"deleted":True,"value":10}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                observation(**fields)

    def test_naive_and_invalid_timestamps_are_rejected(self):
        for stamp in ("2026-01-01", "bad", 0):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                observation(event_at=stamp)

    def test_impossible_chronology_is_rejected(self):
        for name in ("published_at","ingested_at"):
            with self.subTest(field=name), self.assertRaises(ValueError):
                observation(**{name:"2025-12-31T00:00:00Z"})

    def test_negative_nonfinite_and_huge_ttl_are_rejected(self):
        for age in (-1, True, float("inf"), 1e100):
            with self.subTest(age=age), self.assertRaises(ValueError):
                FeatureSpec("tax","revenue",age)

    def test_unknown_features_are_not_silently_dropped(self):
        with self.assertRaises(ValueError):
            snapshot([observation(feature="unknown")])

    def test_unknown_input_columns_are_rejected(self):
        data = demo_inputs()
        data["observations"][0]["future_label"] = 1
        with self.assertRaises(ValueError):
            decode_inputs(data)

    def test_blank_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            observation(entity_id=" ")
