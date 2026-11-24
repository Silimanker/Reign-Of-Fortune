import json
import re
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from . import slots, wallet
from .models import GameRound, Transaction


class SlotEngineTests(SimpleTestCase):
    def test_pay_tier_boundaries(self):
        self.assertIsNone(slots.count_tier(7))
        self.assertEqual(slots.count_tier(8), slots.PAY_TIER_8)
        self.assertEqual(slots.count_tier(9), slots.PAY_TIER_8)
        self.assertEqual(slots.count_tier(10), slots.PAY_TIER_10)
        self.assertEqual(slots.count_tier(11), slots.PAY_TIER_10)
        self.assertEqual(slots.count_tier(12), slots.PAY_TIER_12)

    def test_each_table_has_a_normalized_distribution(self):
        for mode in slots.MODES:
            with self.subTest(mode=mode.slug):
                self.assertAlmostEqual(sum(mode.weights), 1.0)
                self.assertTrue(all(weight > 0 for weight in mode.weights))

    def test_non_winning_chain_keeps_the_actual_grid(self):
        grid = [slots.GRID_KEYS[i % 5] for i in range(slots.CELLS)]
        result = slots.resolve_chain(grid, 1, slots.MODES[0].weights)

        self.assertEqual(result["initial_grid"], grid)
        self.assertEqual(result["final_grid"], grid)
        self.assertEqual(result["steps"], [])

    def test_simulator_distinguishes_any_payout_from_net_positive(self):
        stats = slots.simulate(slots.MODES[0], spins=500, seed=20261102)

        self.assertGreaterEqual(stats["profit_rate"], 0)
        self.assertLessEqual(stats["profit_rate"], stats["hit_rate"])


class SpinFlowTests(TestCase):
    def setUp(self):
        self.player = wallet.ensure_player()

    @staticmethod
    def feature_result():
        return {
            "base": {
                "total": 1.0,
                "steps": [{
                    "grid": ["spirit_leaf"] * slots.CELLS,
                    "cells": list(range(8)),
                    "wins": [{"key": "spirit_leaf", "name": "Spirit Leaf",
                              "count": 8, "tier": slots.PAY_TIER_8, "mult": 2.5}],
                    "mult": 1.0,
                    "payout": 1.0,
                }],
                "initial_grid": ["spirit_leaf"] * slots.CELLS,
                "final_grid": ["jade_bamboo"] * slots.CELLS,
                "scatters": 4,
                "cascades": 1,
            },
            "feature": {
                "count": 4,
                "granted": 10,
                "played": 10,
                "triggerPay": 2.0,
                "total": 12.0,
                "bestMult": 3.0,
                "spins": [{"payout": 10.0, "cascades": 2, "mult": 3.0}],
            },
            "total": 13.0,
            "win": True,
        }

    @patch("game.slots.spin")
    def test_spin_credits_feature_once_and_persists_slot_summary(self, mocked_spin):
        mocked_spin.return_value = self.feature_result()
        response = self.client.post(
            reverse("game:spin"),
            data=json.dumps({"mode": "green-lotus", "stake": 10}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["payout"], "13.00")
        self.assertEqual(payload["grid"], ["jade_bamboo"] * slots.CELLS)

        self.player.refresh_from_db()
        self.assertEqual(self.player.spirit_stones, Decimal("5003.00"))

        round_record = GameRound.objects.get(player=self.player)
        self.assertEqual(round_record.cascade_count, 3)
        self.assertEqual(round_record.free_spins_won, 10)
        self.assertEqual(round_record.feature_outcome["trigger_count"], 4)
        self.assertEqual(round_record.feature_outcome["played"], 10)

        ledger_net = sum(
            row.amount if row.kind in (Transaction.Kind.WIN, Transaction.Kind.BONUS)
            else -row.amount if row.kind == Transaction.Kind.STAKE
            else Decimal("0")
            for row in Transaction.objects.filter(player=self.player)
        )
        self.assertEqual(ledger_net, self.player.spirit_stones - Decimal("5000.00"))
        self.assertEqual(
            Transaction.objects.filter(player=self.player, kind=Transaction.Kind.BONUS)
            .get().amount,
            Decimal("2.00"),
        )

    @patch("game.slots.spin")
    def test_slot_page_provides_working_csrf_token(self, mocked_spin):
        mocked_spin.return_value = self.feature_result()
        client = Client(enforce_csrf_checks=True)
        page = client.get(reverse("game:slot", args=["green-lotus"]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Auto-roll limit")
        self.assertContains(page, 'id="eventAlert"')
        self.assertContains(page, "14% net-positive est.")
        match = re.search(rb'<meta name="csrf-token" content="([^"]+)"', page.content)
        self.assertIsNotNone(match)
        response = client.post(
            reverse("game:spin"),
            data=json.dumps({"mode": "green-lotus", "stake": 10}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=match.group(1).decode(),
        )
        self.assertEqual(response.status_code, 200)

    def test_stake_over_balance_is_rejected_without_writing_a_round(self):
        response = self.client.post(
            reverse("game:spin"),
            data=json.dumps({"mode": "green-lotus", "stake": 6000}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(GameRound.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    @patch("game.slots.spin")
    def test_non_winning_spin_returns_its_actual_grid(self, mocked_spin):
        mocked_spin.return_value = {
            "base": {
                "total": 0.0,
                "steps": [],
                "initial_grid": ["dao_emblem"] + ["phoenix_feather"] * (slots.CELLS - 1),
                "final_grid": ["dao_emblem"] + ["phoenix_feather"] * (slots.CELLS - 1),
                "scatters": 1,
                "cascades": 0,
            },
            "feature": None,
            "total": 0.0,
            "win": False,
        }
        response = self.client.post(
            reverse("game:spin"),
            data=json.dumps({"mode": "green-lotus", "stake": 10}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["grid"][0], "dao_emblem")
        self.assertEqual(response.json()["grid"][1], "phoenix_feather")

    def test_non_object_and_non_finite_stakes_are_rejected(self):
        endpoint = reverse("game:spin")
        for body in (b"[]", b'{"mode":"green-lotus","stake":"NaN"}'):
            with self.subTest(body=body):
                response = self.client.post(
                    endpoint, data=body, content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
