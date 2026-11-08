"""Service acceptance tests for CR-01 express delivery."""

import json
from pathlib import Path
import tempfile
import unittest

from supplydesk.service import OrderService


class ExpressServiceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"
        self.service = OrderService(self.path)

    def test_regular_express_two_notebooks(self):
        before = self.service.catalog()
        quote = self.service.quote("regular", [
            {"product_id": "notebook", "quantity": 2},
        ], "express")

        self.assertEqual(quote["fulfillment"], "express")
        self.assertEqual(quote["subtotal_cents"], 1000)
        self.assertEqual(quote["discount_cents"], 0)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 2200)
        self.assertEqual(quote["items"], [{
            "product_id": "notebook",
            "name": "Notebook",
            "unit_price_cents": 500,
            "quantity": 2,
            "line_total_cents": 1000,
        }])
        self.assertEqual(self.service.catalog(), before)
        self.assertFalse(self.path.exists())

    def test_student_express_two_hoodies(self):
        quote = self.service.quote("student", [
            {"product_id": "hoodie", "quantity": 2},
        ], "express")

        self.assertEqual(quote["subtotal_cents"], 8000)
        self.assertEqual(quote["discount_cents"], 800)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 8400)

    def test_express_fee_applies_when_standard_delivery_is_free(self):
        items = [{"product_id": "hoodie", "quantity": 3}]
        standard = self.service.quote("regular", items, "delivery")
        express = self.service.quote("regular", items, "express")

        self.assertEqual(standard["subtotal_cents"], 12000)
        self.assertEqual(standard["delivery_cents"], 0)
        self.assertEqual(standard["total_cents"], 12000)
        self.assertEqual(express["items"], standard["items"])
        self.assertEqual(express["subtotal_cents"], 12000)
        self.assertEqual(express["discount_cents"], 0)
        self.assertEqual(express["delivery_cents"], 1200)
        self.assertEqual(express["total_cents"], 13200)

    def test_student_express_fee_applies_above_free_delivery_threshold(self):
        items = [{"product_id": "hoodie", "quantity": 3}]
        standard = self.service.quote("student", items, "delivery")
        express = self.service.quote("student", items, "express")

        self.assertEqual(standard["discount_cents"], 1200)
        self.assertEqual(standard["delivery_cents"], 0)
        self.assertEqual(standard["total_cents"], 10800)
        self.assertEqual(express["subtotal_cents"], 12000)
        self.assertEqual(express["discount_cents"], 1200)
        self.assertEqual(express["delivery_cents"], 1200)
        self.assertEqual(express["total_cents"], 12000)

    def test_express_fee_does_not_qualify_merchandise_for_discount(self):
        quote = self.service.quote("student", [
            {"product_id": "notebook", "quantity": 9},
        ], "express")

        self.assertEqual(quote["subtotal_cents"], 4500)
        self.assertEqual(quote["discount_cents"], 0)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 5700)

    def test_express_order_preserves_quote_and_saved_history(self):
        previous = self.service.place_order("regular", [
            {"product_id": "mug", "quantity": 1},
        ])
        catalog_before = self.service.catalog()
        saved_before = self.path.read_bytes()
        items = [{"product_id": "hoodie", "quantity": 2}]

        quote = self.service.quote("student", items, "express")
        self.assertEqual(self.path.read_bytes(), saved_before)
        self.assertEqual(self.service.catalog(), catalog_before)

        order = self.service.place_order("student", items, "express")
        self.assertEqual(order, {
            "order_id": "ORD-0002",
            "status": "placed",
            **quote,
        })
        self.assertEqual(self.service.get_order("ORD-0002"), order)

        reopened = OrderService(self.path)
        self.assertEqual(reopened.get_order("ORD-0002"), order)
        self.assertEqual(reopened.list_orders(), [previous, order])
        stocks = {
            product["product_id"]: product["stock"]
            for product in reopened.catalog()
        }
        self.assertEqual(stocks["hoodie"], 3)
        self.assertEqual(stocks["mug"], 7)
        self.assertEqual(json.loads(self.path.read_text())["schema_version"], 1)

        cancelled = reopened.cancel_order("ORD-0002")
        expected_cancelled = {**order, "status": "cancelled"}
        self.assertEqual(cancelled, expected_cancelled)
        self.assertEqual(reopened.catalog(), catalog_before)

        after_cancel = OrderService(self.path)
        self.assertEqual(after_cancel.get_order("ORD-0002"), expected_cancelled)
        self.assertEqual(after_cancel.list_orders(), [previous, expected_cancelled])
        next_order = after_cancel.place_order("regular", [
            {"product_id": "notebook", "quantity": 1},
        ])
        self.assertEqual(next_order["order_id"], "ORD-0003")
        self.assertEqual(next_order["fulfillment"], "pickup")

    def test_unsupported_fulfillment_preserves_existing_saved_data(self):
        self.service.place_order("regular", [
            {"product_id": "mug", "quantity": 1},
        ])
        saved_before = self.path.read_bytes()
        items = [{"product_id": "notebook", "quantity": 1}]

        for fulfillment in ("courier", "Express", ""):
            for operation in (self.service.quote, self.service.place_order):
                with self.subTest(
                    fulfillment=fulfillment,
                    operation=operation.__name__,
                ):
                    with self.assertRaises(ValueError):
                        operation("regular", items, fulfillment)
                    self.assertEqual(self.path.read_bytes(), saved_before)

    def test_express_placement_rechecks_stock_after_quote(self):
        items = [{"product_id": "hoodie", "quantity": 4}]
        quote = self.service.quote("regular", items, "express")
        self.assertEqual(quote["total_cents"], 17200)

        self.service.place_order("regular", [
            {"product_id": "hoodie", "quantity": 2},
        ])
        saved_before = self.path.read_bytes()

        with self.assertRaises(ValueError):
            self.service.place_order("regular", items, "express")
        self.assertEqual(self.path.read_bytes(), saved_before)

    def test_pickup_default_and_standard_delivery_prices_are_unchanged(self):
        items = [{"product_id": "notebook", "quantity": 2}]
        default = self.service.quote("regular", items)
        pickup = self.service.quote("regular", items, "pickup")
        standard = self.service.quote("regular", items, "delivery")

        self.assertEqual(default, pickup)
        self.assertEqual(default["fulfillment"], "pickup")
        self.assertEqual(default["delivery_cents"], 0)
        self.assertEqual(default["total_cents"], 1000)
        self.assertEqual(standard["delivery_cents"], 600)
        self.assertEqual(standard["total_cents"], 1600)

        at_threshold = self.service.quote("regular", [
            {"product_id": "notebook", "quantity": 20},
        ], "delivery")
        self.assertEqual(at_threshold["subtotal_cents"], 10000)
        self.assertEqual(at_threshold["delivery_cents"], 0)
        self.assertEqual(at_threshold["total_cents"], 10000)


if __name__ == "__main__":
    unittest.main()
