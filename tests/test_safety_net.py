import tempfile
import unittest
from pathlib import Path

from supplydesk.service import OrderService


class SafetyNetTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.path = Path(directory.name) / "state.json"
        self.service = OrderService(self.path)

    def stock(self, product_id):
        for product in self.service.catalog():
            if product["product_id"] == product_id:
                return product["stock"]

        self.fail("Product not found")

    # NORMAL BEHAVIOR

    def test_normal_multiple_product_quote(self):
        quote = self.service.quote("regular", [
            {"product_id": "notebook", "quantity": 2},
            {"product_id": "mug", "quantity": 1},
        ])

        self.assertEqual(len(quote["items"]), 2)
        self.assertEqual(
            [item["line_total_cents"] for item in quote["items"]],
            [1000, 1500],
        )
        self.assertEqual(quote["subtotal_cents"], 2500)
        self.assertEqual(quote["total_cents"], 2500)

    def test_normal_student_delivery_order(self):
        order = self.service.place_order("student", [
            {"product_id": "hoodie", "quantity": 2},
            {"product_id": "mug", "quantity": 1},
        ], "delivery")

        self.assertEqual(order["subtotal_cents"], 9500)
        self.assertEqual(order["discount_cents"], 950)
        self.assertEqual(order["delivery_cents"], 600)
        self.assertEqual(order["total_cents"], 9150)
        self.assertEqual(self.stock("hoodie"), 3)
        self.assertEqual(self.stock("mug"), 7)

        reopened = OrderService(self.path)
        self.assertEqual(
            reopened.get_order(order["order_id"]),
            order,
        )

    def test_normal_order_history(self):
        first = self.service.place_order("regular", [
            {"product_id": "notebook", "quantity": 1},
        ])
        second = self.service.place_order("regular", [
            {"product_id": "mug", "quantity": 1},
        ])

        reopened = OrderService(self.path)

        self.assertEqual(first["order_id"], "ORD-0001")
        self.assertEqual(second["order_id"], "ORD-0002")
        self.assertEqual(
            reopened.list_orders(),
            [first, second],
        )

    # BOUNDARY BEHAVIOR

    def test_boundary_quantity_one(self):
        quote = self.service.quote("regular", [
            {"product_id": "notebook", "quantity": 1},
        ])

        self.assertEqual(quote["items"][0]["quantity"], 1)
        self.assertEqual(quote["total_cents"], 500)

    def test_boundary_zero_quantity(self):
        items = [
            {"product_id": "notebook", "quantity": 0},
        ]

        with self.assertRaises(ValueError):
            self.service.quote("regular", items)

        with self.assertRaises(ValueError):
            self.service.place_order("regular", items)

        self.assertFalse(self.path.exists())

    def test_boundary_student_discount_at_fifty_dollars(self):
        quote = self.service.quote("student", [
            {"product_id": "notebook", "quantity": 10},
        ])

        self.assertEqual(quote["subtotal_cents"], 5000)
        self.assertEqual(quote["discount_cents"], 500)
        self.assertEqual(quote["total_cents"], 4500)

    # INVALID OR EXCEPTIONAL BEHAVIOR

    def test_invalid_quantity_types(self):
        for quantity in (True, 1.5, "2"):
            with self.subTest(quantity=quantity):
                items = [
                    {
                        "product_id": "notebook",
                        "quantity": quantity,
                    },
                ]

                with self.assertRaises(ValueError):
                    self.service.quote("regular", items)

                with self.assertRaises(ValueError):
                    self.service.place_order("regular", items)

                self.assertFalse(self.path.exists())

    def test_invalid_customer_product_or_fulfillment(self):
        cases = [
            ("staff", "notebook", "pickup"),
            ("regular", "missing-product", "pickup"),
            ("regular", "notebook", "courier"),
        ]

        for customer, product, fulfillment in cases:
            with self.subTest(
                customer=customer,
                product=product,
                fulfillment=fulfillment,
            ):
                items = [
                    {"product_id": product, "quantity": 1},
                ]

                with self.assertRaises(ValueError):
                    self.service.quote(
                        customer, items, fulfillment
                    )

                with self.assertRaises(ValueError):
                    self.service.place_order(
                        customer, items, fulfillment
                    )

                self.assertFalse(self.path.exists())

    def test_invalid_duplicate_items_exceed_stock(self):
        self.service.place_order("regular", [
            {"product_id": "mug", "quantity": 1},
        ])
        before = self.path.read_bytes()

        # Combined quantity is 21, but stock is only 20.
        items = [
            {"product_id": "notebook", "quantity": 12},
            {"product_id": "notebook", "quantity": 9},
        ]

        with self.assertRaises(ValueError):
            self.service.place_order("regular", items)

        self.assertEqual(self.path.read_bytes(), before)

    # BEHAVIOR IMPORTANT TO PRESERVE

    def test_preserve_quote_does_not_change_saved_data(self):
        self.service.place_order("regular", [
            {"product_id": "mug", "quantity": 1},
        ])
        before = self.path.read_bytes()

        quote = self.service.quote("student", [
            {"product_id": "hoodie", "quantity": 2},
        ], "delivery")

        self.assertEqual(quote["total_cents"], 7800)
        self.assertEqual(self.path.read_bytes(), before)

        next_order = self.service.place_order("regular", [
            {"product_id": "notebook", "quantity": 1},
        ])
        self.assertEqual(next_order["order_id"], "ORD-0002")

    def test_preserve_placement_rechecks_stock(self):
        items = [
            {"product_id": "hoodie", "quantity": 4},
        ]
        quote = self.service.quote("regular", items)
        self.assertEqual(quote["total_cents"], 16000)

        self.service.place_order("regular", [
            {"product_id": "hoodie", "quantity": 2},
        ])
        before = self.path.read_bytes()

        with self.assertRaises(ValueError):
            self.service.place_order("regular", items)

        self.assertEqual(self.stock("hoodie"), 3)
        self.assertEqual(self.path.read_bytes(), before)

    def test_preserve_repeated_cancellation(self):
        order = self.service.place_order("regular", [
            {"product_id": "notebook", "quantity": 2},
        ])

        self.service.cancel_order(order["order_id"])
        self.assertEqual(self.stock("notebook"), 20)

        self.service.cancel_order(order["order_id"])
        self.assertEqual(self.stock("notebook"), 20)
        self.assertEqual(
            self.service.get_order(order["order_id"])["status"],
            "cancelled",
        )
        self.assertEqual(len(self.service.list_orders()), 1)


if __name__ == "__main__":
    unittest.main()