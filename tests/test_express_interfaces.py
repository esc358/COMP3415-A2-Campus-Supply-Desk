"""End-to-end command and menu checks for CR-01 express delivery."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ExpressInterfaceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"

    def run_command(self, *arguments, input_text=None):
        return subprocess.run(
            [sys.executable, "-m", "supplydesk", "--data", str(self.path), *arguments],
            input=input_text,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            timeout=10,
        )

    def test_quote_command_supports_express_without_saving(self):
        result = self.run_command(
            "quote", "--item", "notebook:2", "--fulfillment", "express",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        quote = json.loads(result.stdout)
        self.assertEqual(quote["customer_type"], "regular")
        self.assertEqual(quote["fulfillment"], "express")
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 2200)
        self.assertFalse(self.path.exists())

    def test_place_command_saves_express_for_later_lookup(self):
        request = (
            "--customer", "student", "--item", "hoodie:2",
            "--fulfillment", "express",
        )
        quoted = self.run_command("quote", *request)
        self.assertEqual(quoted.returncode, 0, quoted.stderr)
        quote = json.loads(quoted.stdout)

        placed = self.run_command("place", *request)
        self.assertEqual(placed.returncode, 0, placed.stderr)
        order = json.loads(placed.stdout)
        self.assertEqual(order, {
            "order_id": "ORD-0001",
            "status": "placed",
            **quote,
        })
        self.assertEqual(order["discount_cents"], 800)
        self.assertEqual(order["delivery_cents"], 1200)
        self.assertEqual(order["total_cents"], 8400)

        retrieved = self.run_command("show", order["order_id"])
        self.assertEqual(retrieved.returncode, 0, retrieved.stderr)
        self.assertEqual(json.loads(retrieved.stdout), order)

    def test_quote_and_place_help_advertise_express_fee(self):
        for command in ("quote", "place"):
            with self.subTest(command=command):
                result = self.run_command(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("express", result.stdout)
                self.assertIn("$12.00", result.stdout)

    def test_menu_quotes_and_places_express_with_confirmation(self):
        result = self.run_command(input_text="\n".join([
            "2", "", "notebook", "2", "", "express",
            "3", "", "notebook", "2", "", "express", "y",
            "0", "",
        ]))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pickup/delivery/express", result.stdout)
        self.assertIn("$12.00", result.stdout)
        self.assertIn("Total: $22.00", result.stdout)

        state = json.loads(self.path.read_text())
        self.assertEqual(len(state["orders"]), 1)
        order = state["orders"][0]
        self.assertEqual(order["order_id"], "ORD-0001")
        self.assertEqual(order["customer_type"], "regular")
        self.assertEqual(order["fulfillment"], "express")
        self.assertEqual(order["delivery_cents"], 1200)
        self.assertEqual(order["total_cents"], 2200)
        self.assertEqual(state["next_order_number"], 2)
        stocks = {
            product["product_id"]: product["stock"]
            for product in state["catalog"]
        }
        self.assertEqual(stocks["notebook"], 18)


if __name__ == "__main__":
    unittest.main()
