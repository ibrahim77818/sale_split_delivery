# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def _is_child_of(location, parent):
    """True when ``location`` is ``parent`` or one of its descendants."""
    return bool(location and parent and location.parent_path
                and parent.parent_path
                and location.parent_path.startswith(parent.parent_path))


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    # Odoo 16 has no line-level delivery date (purchase.order.line has
    # ``date_planned`` "Expected Arrival"). This is its sales counterpart:
    # stored, follows the order Delivery Date (commitment_date) like the PO
    # header date follows into its lines, and stays editable per line.
    expected_delivery_date = fields.Datetime(
        string='Expected Delivery',
        compute='_compute_expected_delivery_date',
        store=True, readonly=False, precompute=True, copy=False,
        help='Date this line is expected to reach the customer. It follows '
             'the order Delivery Date and can be changed per line; when '
             'empty, the product lead time is used.')
    delivery_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Delivery Warehouse',
        compute='_compute_delivery_warehouse_id',
        store=True, readonly=False, precompute=True, check_company=True,
        help='Warehouse this line is shipped from. Defaults to the order '
             'warehouse.')
    delivery_location_id = fields.Many2one(
        'stock.location', string='Source Location',
        compute='_compute_delivery_location_id',
        store=True, readonly=False, precompute=True, check_company=True,
        domain="[('usage', '=', 'internal'), "
               "('warehouse_id', '=', delivery_warehouse_id)]",
        help='Stock location the goods of this line are picked from. '
             'Defaults to the warehouse stock location.')

    # ------------------------------------------------------------------
    # Computes & constraints
    # ------------------------------------------------------------------
    @api.depends('order_id.commitment_date', 'display_type')
    def _compute_expected_delivery_date(self):
        for line in self:
            line.expected_delivery_date = (
                False if line.display_type else line.order_id.commitment_date)

    @api.depends('order_id.warehouse_id', 'display_type')
    def _compute_delivery_warehouse_id(self):
        for line in self:
            line.delivery_warehouse_id = (
                False if line.display_type else line.order_id.warehouse_id)

    @api.depends('delivery_warehouse_id')
    def _compute_delivery_location_id(self):
        for line in self:
            line.delivery_location_id = line.delivery_warehouse_id.lot_stock_id

    @api.constrains('delivery_location_id', 'delivery_warehouse_id')
    def _check_delivery_location_warehouse(self):
        for line in self:
            location = line.delivery_location_id
            warehouse = line.delivery_warehouse_id
            if not location or not warehouse:
                continue
            if location.usage != 'internal' or not _is_child_of(
                    location, warehouse.view_location_id):
                raise ValidationError(_(
                    'The source location "%(location)s" of the order line '
                    '"%(line)s" must be an internal location of the '
                    'warehouse "%(warehouse)s".',
                    location=location.display_name,
                    line=line.name,
                    warehouse=warehouse.display_name,
                ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _sale_split_company(self):
        self.ensure_one()
        return self.order_id.company_id or self.env.company

    def _sale_split_get_deadline(self):
        """Effective date the goods of this line must reach the customer."""
        self.ensure_one()
        if self.expected_delivery_date:
            return self.expected_delivery_date
        order = self.order_id
        if order.commitment_date:
            return order.commitment_date
        return (order.date_order or fields.Datetime.now()) + timedelta(
            days=self.customer_lead or 0.0)

    def _sale_split_local_date(self, value):
        """Calendar day of ``value`` in the salesperson's time zone, so that
        two lines planned on the same local day share one delivery order."""
        self.ensure_one()
        if not value:
            return False
        tz = self.order_id.user_id.tz or self.env.user.tz or 'UTC'
        return fields.Datetime.context_timestamp(
            self.with_context(tz=tz), value).date()

    def _sale_split_target_location(self, rule_location):
        """Location a move created by a rule sourcing from ``rule_location``
        should pick from for this line."""
        self.ensure_one()
        location = self.delivery_location_id
        if _is_child_of(location, rule_location):
            return location
        return rule_location

    # ------------------------------------------------------------------
    # Standard overrides
    # ------------------------------------------------------------------
    def _expected_date(self):
        self.ensure_one()
        if (self.expected_delivery_date
                and self._sale_split_company()._sale_split_enabled('date')):
            return self.expected_delivery_date
        return super()._expected_date()

    def _prepare_procurement_values(self, group_id=False):
        values = super()._prepare_procurement_values(group_id=group_id)
        company = self._sale_split_company()
        if not company.sale_split_delivery:
            return values
        if company.sale_split_by_date:
            if self.expected_delivery_date:
                deadline = self.expected_delivery_date
                values['date_deadline'] = deadline
                values['date_planned'] = deadline - timedelta(
                    days=company.security_lead or 0.0)
            values['sale_split_date'] = self._sale_split_local_date(
                values.get('date_deadline') or self._sale_split_get_deadline())
        if company.sale_split_by_warehouse and self.delivery_warehouse_id:
            values['warehouse_id'] = self.delivery_warehouse_id
        if company.sale_split_by_location and self.delivery_location_id:
            values['sale_split_location_id'] = self.delivery_location_id
        return values

    def write(self, vals):
        if 'delivery_warehouse_id' in vals:
            for line in self:
                if (line.state == 'sale'
                        and line.delivery_warehouse_id.id != vals['delivery_warehouse_id']
                        and line.move_ids.filtered(lambda m: m.state != 'cancel')):
                    raise UserError(_(
                        'The warehouse of the confirmed order line "%s" '
                        'cannot be changed because delivery transfers '
                        'already exist for it.', line.name))
        res = super().write(vals)
        if {'expected_delivery_date', 'delivery_location_id'} & set(vals):
            self._sale_split_resync_moves()
        return res

    # ------------------------------------------------------------------
    # Post-confirmation maintenance
    # ------------------------------------------------------------------
    def _sale_split_pending_moves(self):
        """Outgoing move chain of the line (ship, pack, pick) that can still
        be re-planned: same procurement group, nothing processed yet."""
        self.ensure_one()
        group = self.order_id.procurement_group_id
        moves = self.env['stock.move'].sudo()
        todo = self.move_ids.sudo().filtered(
            lambda m: m.location_dest_id.usage == 'customer'
            and not m.origin_returned_move_id)
        while todo:
            moves |= todo
            todo = todo.move_orig_ids.filtered(
                lambda m: m.group_id == group) - moves
        return moves.filtered(
            lambda m: m.state not in ('done', 'cancel')
            and not m.picked
            and m.picking_id.state not in ('done', 'cancel'))

    def _sale_split_resync_moves(self):
        """Realign pending moves with the line date/location, move them to
        the matching delivery order and delete the ones left empty.

        Idempotent: moves already matching are left untouched.
        """
        Move = self.env['stock.move'].sudo()
        old_pickings = self.env['stock.picking'].sudo()
        for line in self:
            if line.state != 'sale' or line.display_type:
                continue
            company = line._sale_split_company()
            by_date = company._sale_split_enabled('date')
            by_location = company._sale_split_enabled('location')
            if not (by_date or by_location):
                continue
            chain = line._sale_split_pending_moves()
            if not chain:
                continue
            to_reassign = Move
            if by_date:
                deadline = line._sale_split_get_deadline()
                split_date = line._sale_split_local_date(deadline)
                for move in chain:
                    move_vals = {}
                    if move.date_deadline != deadline:
                        move_vals['date_deadline'] = deadline
                        if move.date_deadline:
                            move_vals['date'] = move.date + (deadline - move.date_deadline)
                    if move.sale_split_date != split_date:
                        move_vals['sale_split_date'] = split_date
                    if move_vals:
                        move.write(move_vals)
                    if move.picking_id.sale_split_date != split_date:
                        to_reassign |= move
            if by_location:
                for move in chain:
                    rule_location = move.rule_id.location_src_id
                    if not rule_location or rule_location.usage != 'internal':
                        continue
                    target = line._sale_split_target_location(rule_location)
                    move_vals = {}
                    if move.sale_split_location_id != line.delivery_location_id:
                        move_vals['sale_split_location_id'] = line.delivery_location_id.id
                    if move.location_id != target:
                        move_vals['location_id'] = target.id
                        to_reassign |= move
                    if move_vals:
                        if 'location_id' in move_vals and move.state in (
                                'assigned', 'partially_available'):
                            move._do_unreserve()
                        move.write(move_vals)
            if not to_reassign:
                continue
            reserved = to_reassign.filtered(
                lambda m: m.state in ('assigned', 'partially_available'))
            if reserved:
                reserved._do_unreserve()
            old_pickings |= to_reassign.picking_id
            to_reassign.write({'picking_id': False})
            to_reassign._assign_picking()
            to_reassign._action_assign()
        self._sale_split_cleanup_pickings(old_pickings)

    def _sale_split_cleanup_pickings(self, pickings):
        empty = pickings.exists().filtered(
            lambda p: not p.move_ids and p.state not in ('done', 'cancel'))
        if not empty:
            return
        by_order = {}
        for picking in empty:
            if picking.sale_id:
                by_order.setdefault(picking.sale_id, []).append(picking.name)
        empty.unlink()
        for order, names in by_order.items():
            order.message_post(body=_(
                'Empty delivery transfers removed after rescheduling: %s',
                ', '.join(names)))
