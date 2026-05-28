import copy
import unittest
from pathlib import Path

from scripts.select_and_launch import (
    effective_cost,
    is_preferred_machine,
    load_launch_context,
    offer_passes_policy,
    search_policy_offers,
    selection_sort_key,
)


def load_context():
    return load_launch_context(Path("config/launch-profiles/qwen3.5-9b-awq.interruptible.json"))


def good_offer(**overrides):
    offer = {
        "id": 123,
        "machine_id": 1569,
        "gpu_name": "RTX 5090",
        "num_gpus": 1,
        "gpu_total_ram": 32000,
        "cuda_max_good": 13.0,
        "dph_total": 0.30,
        "dph_base": 0.28,
        "storage_total_cost": 0.005,
        "disk_bw": 1000,
        "internet_down_cost_per_tb": 2.0,
        "internet_up_cost_per_tb": 3.0,
        "inet_down": 2000,
        "direct_port_count": 1,
        "reliability2": 0.995,
        "disk_space": 80,
    }
    offer.update(overrides)
    return offer


class OfferPolicyTests(unittest.TestCase):
    def setUp(self):
        self.context = load_context()

    def assertFailsFor(self, reason, **offer_overrides):
        ok, reasons = offer_passes_policy(good_offer(**offer_overrides), self.context)
        self.assertFalse(ok)
        self.assertIn(reason, reasons)

    def test_good_offer_passes(self):
        ok, reasons = offer_passes_policy(good_offer(), self.context)
        self.assertTrue(ok, reasons)

    def test_greylisted_machine_fails(self):
        self.assertFailsFor("greylisted_machine", machine_id=8357)

    def test_deverified_offer_fails(self):
        self.assertFailsFor("deverified", verification="deverified")

    def test_unverified_offer_passes(self):
        ok, reasons = offer_passes_policy(good_offer(verification="unverified"), self.context)
        self.assertTrue(ok, reasons)

    def test_disallowed_gpu_fails(self):
        self.assertFailsFor("allowed_gpu_names", gpu_name="Tesla P40")

    def test_low_gpu_ram_fails_using_mb_offer_units(self):
        self.assertFailsFor("gpu_total_ram", gpu_total_ram=20000)

    def test_low_network_fails(self):
        self.assertFailsFor("inet_down", inet_down=999)

    def test_low_disk_bandwidth_fails(self):
        self.assertFailsFor("disk_bw", disk_bw=499)

    def test_high_total_price_fails(self):
        self.assertFailsFor("dph_total", dph_total=999)

    def test_high_storage_cost_fails(self):
        self.assertFailsFor("storage_total_cost", storage_total_cost=999)

    def test_high_bandwidth_costs_fail(self):
        self.assertFailsFor("internet_down_cost_per_tb", internet_down_cost_per_tb=999)
        self.assertFailsFor("internet_up_cost_per_tb", internet_up_cost_per_tb=999)

    def test_low_reliability_fails(self):
        self.assertFailsFor("reliability2", reliability2=0.5)

    def test_effective_cost_includes_expected_download_cost(self):
        context = copy.deepcopy(self.context)
        context["launch"]["selection"]["expected_model_download_tb"] = 0.5
        offer = good_offer(dph_total=1.0, internet_down_cost_per_tb=2.0)
        self.assertEqual(effective_cost(offer, context), 2.0)

    def test_preferred_sort_wins_before_lower_effective_cost(self):
        preferred = good_offer(id=1, machine_id=1569, dph_total=0.60)
        non_preferred = good_offer(id=2, machine_id=99999, dph_total=0.10)
        offers = sorted([non_preferred, preferred], key=lambda o: selection_sort_key(o, self.context))
        self.assertEqual(offers[0]["id"], 1)
        self.assertTrue(is_preferred_machine(preferred, self.context))


class SearchPolicyOffersTests(unittest.TestCase):
    def test_query_uses_gpu_ram_gb_and_interruptible_market(self):
        context = load_context()

        class FakeVast:
            def __init__(self):
                self.calls = []

            def search_offers(self, **kwargs):
                self.calls.append(kwargs)
                return [good_offer()]

        fake = FakeVast()
        offers = search_policy_offers(fake, context)
        self.assertEqual(len(offers), 1)
        call = fake.calls[0]
        self.assertEqual(call["type"], "interruptible")
        self.assertIn("gpu_total_ram>=21.0", call["query"])
        self.assertIn("verified=true", call["query"])
        self.assertIn("verification!=deverified", call["query"])

    def test_search_drops_deverified_before_policy_output(self):
        context = load_context()
        context["launch"]["reliability"]["require_verified"] = False

        class FakeVast:
            def __init__(self):
                self.calls = []

            def search_offers(self, **kwargs):
                self.calls.append(kwargs)
                return [
                    good_offer(id=1, verification="deverified"),
                    good_offer(id=2, verification="unverified"),
                ]

        fake = FakeVast()
        offers = search_policy_offers(fake, context)
        self.assertEqual([offer["id"] for offer in offers], [2])
        self.assertIn("verification!=deverified", fake.calls[0]["query"])

    def test_on_demand_market_mapping(self):
        context = load_context()
        context["launch"]["market"] = "on-demand"

        class FakeVast:
            def __init__(self):
                self.calls = []

            def search_offers(self, **kwargs):
                self.calls.append(kwargs)
                return [good_offer()]

        fake = FakeVast()
        search_policy_offers(fake, context)
        self.assertEqual(fake.calls[0]["type"], "on-demand")

    def test_explicit_gpu_configs_allow_mixed_gpu_counts(self):
        context = load_context()
        context["gpu"] = {
            "allowed_gpu_configs": [
                {"gpu_name": "RTX 5060 Ti", "num_gpus": 2, "min_gpu_total_ram_mb": 30000},
                {"gpu_name": "RTX 5090", "num_gpus": 1, "min_gpu_total_ram_mb": 30000},
            ],
            "min_gpu_total_ram_mb": 30000,
            "min_cuda_max_good": 13.0,
        }

        ok, reasons = offer_passes_policy(good_offer(gpu_name="RTX 5060 Ti", num_gpus=2, gpu_total_ram=32000), context)
        self.assertTrue(ok, reasons)

        ok, reasons = offer_passes_policy(good_offer(gpu_name="RTX 5060 Ti", num_gpus=1, gpu_total_ram=16000), context)
        self.assertFalse(ok)
        self.assertIn("num_gpus", reasons)

    def test_explicit_gpu_configs_search_each_gpu_count(self):
        context = load_context()
        context["launch"]["market"] = "on-demand"
        context["gpu"] = {
            "allowed_gpu_configs": [
                {"gpu_name": "RTX 5060 Ti", "num_gpus": 2, "min_gpu_total_ram_mb": 30000},
                {"gpu_name": "RTX 5090", "num_gpus": 1, "min_gpu_total_ram_mb": 30000},
            ],
            "min_gpu_total_ram_mb": 30000,
            "min_cuda_max_good": 13.0,
        }

        class FakeVast:
            def __init__(self):
                self.calls = []

            def search_offers(self, **kwargs):
                self.calls.append(kwargs)
                if 'gpu_name="RTX 5060 Ti"' in kwargs["query"]:
                    return [good_offer(id=1, gpu_name="RTX 5060 Ti", num_gpus=2, gpu_total_ram=32000)]
                return [good_offer(id=2, gpu_name="RTX 5090", num_gpus=1, gpu_total_ram=32000)]

        fake = FakeVast()
        offers = search_policy_offers(fake, context)
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(any("num_gpus=2" in call["query"] for call in fake.calls))
        self.assertTrue(any("num_gpus=1" in call["query"] for call in fake.calls))
        self.assertEqual({offer["id"] for offer in offers}, {1, 2})


if __name__ == "__main__":
    unittest.main()
