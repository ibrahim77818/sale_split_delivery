# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # View helpers (column visibility on the order lines)
    sale_split_by_date_enabled = fields.Boolean(
        string='Delivery Date Split Enabled',
        compute='_compute_sale_split_enabled')
    sale_split_by_location_enabled = fields.Boolean(
        string='Source Location Split Enabled',
        compute='_compute_sale_split_enabled')
    sale_split_by_warehouse_enabled = fields.Boolean(
        string='Warehouse Split Enabled',
        compute='_compute_sale_split_enabled')

    @api.depends('company_id')
    def _compute_sale_split_enabled(self):
        for order in self:
            company = order.company_id or self.env.company
            order.sale_split_by_date_enabled = company._sale_split_enabled('date')
            order.sale_split_by_location_enabled = company._sale_split_enabled('location')
            order.sale_split_by_warehouse_enabled = company._sale_split_enabled('warehouse')

    @api.depends('order_line.expected_delivery_date')
    def _compute_expected_date(self):
        # Extra dependency only: line dates feed sale.order.line._expected_date()
        return super()._compute_expected_date()

    def write(self, vals):
        res = super().write(vals)
        if 'commitment_date' in vals:
            # The new Delivery Date is pushed to the lines by their compute;
            # realign the pending moves and pickings accordingly.
            self.filtered(lambda o: o.state == 'sale').order_line._sale_split_resync_moves()
        return res
