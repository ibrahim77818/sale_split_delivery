# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'sale_split_delivery')
class TestSaleSplitDelivery(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.stock = cls.warehouse.lot_stock_id
        Location = cls.env['stock.location']
        cls.shelf_a = Location.create({
            'name': 'Split Shelf A', 'location_id': cls.stock.id, 'usage': 'internal'})
        cls.shelf_b = Location.create({
            'name': 'Split Shelf B', 'location_id': cls.stock.id, 'usage': 'internal'})

        cls.warehouse_2 = cls.env['stock.warehouse'].create({
            'name': 'Split WH 2', 'code': 'SWH2', 'company_id': cls.company.id})
        cls.warehouse_3 = cls.env['stock.warehouse'].create({
            'name': 'Split WH 3', 'code': 'SWH3', 'company_id': cls.company.id,
            'delivery_steps': 'pick_ship'})
        cls.shelf_c1 = Location.create({
            'name': 'Split Shelf C1', 'usage': 'internal',
            'location_id': cls.warehouse_3.lot_stock_id.id})
        cls.shelf_c2 = Location.create({
            'name': 'Split Shelf C2', 'usage': 'internal',
            'location_id': cls.warehouse_3.lot_stock_id.id})

        cls.partner = cls.env['res.partner'].create({'name': 'Split Customer'})
        Product = cls.env['product.product']
        cls.product_1 = Product.create({'name': 'Split Product 1', 'detailed_type': 'product'})
        cls.product_2 = Product.create({'name': 'Split Product 2', 'detailed_type': 'product'})
        cls.product_3 = Product.create({'name': 'Split Product 3', 'detailed_type': 'product'})

        Quant = cls.env['stock.quant']
        for product in (cls.product_1, cls.product_2, cls.product_3):
            for location in (cls.shelf_a, cls.shelf_b, cls.shelf_c1, cls.shelf_c2,
                             cls.warehouse_2.lot_stock_id):
                Quant._update_available_quantity(product, location, 50.0)

        # Noon UTC keeps the local day stable for any salesperson time zone.
        cls.date_1 = datetime(2031, 3, 10, 12, 0)
        cls.date_2 = datetime(2031, 3, 17, 12, 0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _configure(self, master=True, by_date=False, by_location=False, by_warehouse=False):
        self.company.write({
            'sale_split_delivery': master,
            'sale_split_by_date': by_date,
            'sale_split_by_location': by_location,
            'sale_split_by_warehouse': by_warehouse,
        })

    def _create_order(self, lines, warehouse=None, **order_vals):
        line_commands = []
        for spec in lines:
            vals = {
                'product_id': spec['product'].id,
                'product_uom_qty': spec.get('qty', 1.0),
            }
            if 'date' in spec:
                vals['expected_delivery_date'] = spec['date']
            if 'warehouse' in spec:
                vals['delivery_warehouse_id'] = spec['warehouse'].id
            if 'location' in spec:
                vals['delivery_location_id'] = spec['location'].id
            line_commands.append((0, 0, vals))
        return self.env['sale.order'].create(dict(
            order_vals,
            partner_id=self.partner.id,
            warehouse_id=(warehouse or self.warehouse).id,
            order_line=line_commands,
        ))

    def _deliveries(self, order, picking_type=None):
        domain = [('sale_id', '=', order.id), ('state', '!=', 'cancel')]
        if picking_type:
            domain.append(('picking_type_id', '=', picking_type.id))
        return self.env['stock.picking'].search(domain)

    def _picking_of(self, line, picking_type=None):
        moves = line.move_ids
        if picking_type:
            moves = line.order_id.procurement_group_id.stock_move_ids.filtered(
                lambda m: m.picking_type_id == picking_type and m.product_id == line.product_id)
        return moves.picking_id

    # ------------------------------------------------------------------
    # Expected Delivery field
    # ------------------------------------------------------------------
    def test_01_expected_delivery_follows_commitment_date(self):
        self._configure(by_date=True)
        order = self._create_order(
            [{'product': self.product_1}, {'product': self.product_2}],
            commitment_date=self.date_1)
        self.assertEqual(order.order_line.mapped('expected_delivery_date'),
                         [self.date_1, self.date_1])
        order.commitment_date = self.date_2
        self.assertEqual(order.order_line.mapped('expected_delivery_date'),
                         [self.date_2, self.date_2])
        # Per-line override is kept until the order date changes again
        order.order_line[0].expected_delivery_date = self.date_1
        self.assertEqual(order.order_line[0].expected_delivery_date, self.date_1)
        self.assertEqual(order.order_line[1].expected_delivery_date, self.date_2)

    def test_02_order_expected_date_uses_line_dates(self):
        self._configure(by_date=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_2},
            {'product': self.product_2, 'date': self.date_1},
        ], picking_policy='direct')
        self.assertEqual(order.expected_date, self.date_1)
        order.picking_policy = 'one'
        self.assertEqual(order.expected_date, self.date_2)

    # ------------------------------------------------------------------
    # Splitting on confirmation
    # ------------------------------------------------------------------
    def test_10_disabled_keeps_standard_single_delivery(self):
        self._configure(master=False, by_date=True, by_location=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_1, 'location': self.shelf_a},
            {'product': self.product_2, 'date': self.date_2, 'location': self.shelf_b},
        ])
        order.action_confirm()
        pickings = self._deliveries(order)
        self.assertEqual(len(pickings), 1)
        self.assertEqual(pickings.location_id, self.stock)
        self.assertFalse(pickings.sale_split_date)

    def test_11_split_by_date(self):
        self._configure(by_date=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_1},
            {'product': self.product_2, 'date': self.date_2},
            {'product': self.product_3, 'date': self.date_1},
        ])
        order.action_confirm()
        pickings = self._deliveries(order)
        self.assertEqual(len(pickings), 2)
        line_1, line_2, line_3 = order.order_line
        self.assertEqual(self._picking_of(line_1), self._picking_of(line_3))
        self.assertNotEqual(self._picking_of(line_1), self._picking_of(line_2))
        self.assertEqual(line_1.move_ids.date_deadline, self.date_1)
        self.assertEqual(line_2.move_ids.date_deadline, self.date_2)
        self.assertEqual(self._picking_of(line_2).sale_split_date,
                         line_2._sale_split_local_date(self.date_2))

    def test_12_split_by_date_without_line_dates_stays_grouped(self):
        self._configure(by_date=True)
        order = self._create_order([{'product': self.product_1}, {'product': self.product_2}])
        order.action_confirm()
        self.assertEqual(len(self._deliveries(order)), 1)

    def test_13_split_by_location(self):
        self._configure(by_location=True)
        order = self._create_order([
            {'product': self.product_1, 'location': self.shelf_a},
            {'product': self.product_2, 'location': self.shelf_b},
            {'product': self.product_3, 'location': self.shelf_a},
        ])
        order.action_confirm()
        pickings = self._deliveries(order)
        self.assertEqual(len(pickings), 2)
        self.assertEqual(set(pickings.mapped('location_id').ids),
                         {self.shelf_a.id, self.shelf_b.id})
        line_1, line_2, _line_3 = order.order_line
        self.assertEqual(line_1.move_ids.location_id, self.shelf_a)
        self.assertEqual(line_2.move_ids.location_id, self.shelf_b)

    def test_14_split_by_date_and_location(self):
        self._configure(by_date=True, by_location=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_1, 'location': self.shelf_a},
            {'product': self.product_2, 'date': self.date_1, 'location': self.shelf_b},
            {'product': self.product_3, 'date': self.date_2, 'location': self.shelf_a},
            {'product': self.product_1, 'date': self.date_2, 'location': self.shelf_a, 'qty': 2},
        ])
        order.action_confirm()
        pickings = self._deliveries(order)
        self.assertEqual(len(pickings), 3)
        keys = {(p.sale_split_date, p.location_id.id) for p in pickings}
        line = order.order_line[0]
        day_1 = line._sale_split_local_date(self.date_1)
        day_2 = line._sale_split_local_date(self.date_2)
        self.assertEqual(keys, {
            (day_1, self.shelf_a.id), (day_1, self.shelf_b.id), (day_2, self.shelf_a.id)})

    def test_15_split_by_warehouse(self):
        self._configure(by_warehouse=True)
        order = self._create_order([
            {'product': self.product_1},
            {'product': self.product_2, 'warehouse': self.warehouse_2},
        ])
        line_2 = order.order_line[1]
        self.assertEqual(line_2.delivery_location_id, self.warehouse_2.lot_stock_id)
        order.action_confirm()
        pickings = self._deliveries(order)
        self.assertEqual(len(pickings), 2)
        self.assertEqual(set(pickings.mapped('picking_type_id').ids),
                         {self.warehouse.out_type_id.id, self.warehouse_2.out_type_id.id})
        self.assertEqual(self._picking_of(line_2).picking_type_id, self.warehouse_2.out_type_id)

    def test_16_multi_step_route_splits_pick_step(self):
        self._configure(by_location=True, by_date=True)
        wh = self.warehouse_3
        order = self._create_order([
            {'product': self.product_1, 'location': self.shelf_c1, 'date': self.date_1},
            {'product': self.product_2, 'location': self.shelf_c2, 'date': self.date_1},
            {'product': self.product_3, 'location': self.shelf_c1, 'date': self.date_2},
        ], warehouse=wh)
        order.action_confirm()
        picks = self._deliveries(order, wh.pick_type_id)
        ships = self._deliveries(order, wh.out_type_id)
        # pick: (day1, C1) (day1, C2) (day2, C1) ; ship: day1, day2
        self.assertEqual(len(picks), 3)
        self.assertEqual(len(ships), 2)
        self.assertEqual(set(picks.mapped('location_id').ids), {self.shelf_c1.id, self.shelf_c2.id})
        self.assertEqual(ships.location_id, wh.wh_output_stock_loc_id)

    # ------------------------------------------------------------------
    # Post-confirmation maintenance
    # ------------------------------------------------------------------
    def test_20_date_change_merges_and_removes_empty_delivery(self):
        self._configure(by_date=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_1},
            {'product': self.product_2, 'date': self.date_2},
        ])
        order.action_confirm()
        line_1, line_2 = order.order_line
        old_picking = self._picking_of(line_2)
        self.assertEqual(len(self._deliveries(order)), 2)

        line_2.expected_delivery_date = self.date_1
        self.assertFalse(old_picking.exists())
        self.assertEqual(len(self._deliveries(order)), 1)
        self.assertEqual(self._picking_of(line_2), self._picking_of(line_1))
        self.assertEqual(line_2.move_ids.date_deadline, self.date_1)

    def test_21_date_change_splits_into_new_delivery(self):
        self._configure(by_date=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_1},
            {'product': self.product_2, 'date': self.date_1},
        ])
        order.action_confirm()
        self.assertEqual(len(self._deliveries(order)), 1)
        line_2 = order.order_line[1]
        line_2.expected_delivery_date = self.date_2
        pickings = self._deliveries(order)
        self.assertEqual(len(pickings), 2)
        self.assertEqual(self._picking_of(line_2).sale_split_date,
                         line_2._sale_split_local_date(self.date_2))

    def test_22_commitment_date_change_regroups(self):
        self._configure(by_date=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_1},
            {'product': self.product_2, 'date': self.date_2},
        ])
        order.action_confirm()
        self.assertEqual(len(self._deliveries(order)), 2)
        order.commitment_date = self.date_2
        self.assertEqual(len(self._deliveries(order)), 1)
        self.assertEqual(order.order_line.move_ids.mapped('date_deadline'),
                         [self.date_2, self.date_2])

    def test_23_location_change_reroutes_moves(self):
        self._configure(by_location=True)
        order = self._create_order([
            {'product': self.product_1, 'location': self.shelf_a},
            {'product': self.product_2, 'location': self.shelf_b},
        ])
        order.action_confirm()
        line_2 = order.order_line[1]
        old_picking = self._picking_of(line_2)
        line_2.delivery_location_id = self.shelf_a
        self.assertFalse(old_picking.exists())
        pickings = self._deliveries(order)
        self.assertEqual(len(pickings), 1)
        self.assertEqual(pickings.location_id, self.shelf_a)
        self.assertEqual(line_2.move_ids.location_id, self.shelf_a)
        self.assertEqual(line_2.move_ids.move_line_ids.location_id, self.shelf_a)

    def test_24_quantity_increase_lands_in_matching_delivery(self):
        self._configure(by_date=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_1},
            {'product': self.product_2, 'date': self.date_2},
        ])
        order.action_confirm()
        line_1 = order.order_line[0]
        picking_1 = self._picking_of(line_1)
        line_1.product_uom_qty = 3.0
        self.assertEqual(len(self._deliveries(order)), 2)
        moves = picking_1.move_ids.filtered(lambda m: m.product_id == self.product_1)
        self.assertEqual(sum(moves.mapped('product_uom_qty')), 3.0)

    def test_25_processed_moves_are_not_moved(self):
        self._configure(by_date=True)
        order = self._create_order([
            {'product': self.product_1, 'date': self.date_1},
            {'product': self.product_2, 'date': self.date_2},
        ])
        order.action_confirm()
        line_2 = order.order_line[1]
        picking_2 = self._picking_of(line_2)
        picking_2.move_ids.quantity_done = 1.0
        picking_2._action_done()
        line_2.expected_delivery_date = self.date_1
        self.assertTrue(picking_2.exists())
        self.assertEqual(picking_2.state, 'done')

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def test_30_location_must_belong_to_line_warehouse(self):
        self._configure(by_location=True, by_warehouse=True)
        with self.assertRaises(ValidationError):
            self._create_order([{'product': self.product_1,
                                 'location': self.warehouse_2.lot_stock_id}])

    def test_31_warehouse_locked_after_confirmation(self):
        self._configure(by_warehouse=True)
        order = self._create_order([{'product': self.product_1}])
        order.action_confirm()
        with self.assertRaises(UserError):
            order.order_line.delivery_warehouse_id = self.warehouse_2

    def test_32_unrelated_receipts_unaffected(self):
        """Pickings created outside sales still group as in standard."""
        self._configure(by_date=True, by_location=True)
        supplier = self.env.ref('stock.stock_location_suppliers')
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.in_type_id.id,
            'location_id': supplier.id,
            'location_dest_id': self.stock.id,
            'move_ids': [(0, 0, {
                'name': p.name, 'product_id': p.id, 'product_uom_qty': 1.0,
                'product_uom': p.uom_id.id, 'location_id': supplier.id,
                'location_dest_id': self.stock.id,
            }) for p in (self.product_1, self.product_2)],
        })
        picking.action_confirm()
        self.assertEqual(len(picking.move_ids), 2)
        self.assertFalse(picking.sale_split_date)
