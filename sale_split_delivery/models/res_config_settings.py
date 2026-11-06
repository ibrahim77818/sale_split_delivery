# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sale_split_delivery = fields.Boolean(
        related='company_id.sale_split_delivery', readonly=False)
    sale_split_by_date = fields.Boolean(
        related='company_id.sale_split_by_date', readonly=False)
    sale_split_by_location = fields.Boolean(
        related='company_id.sale_split_by_location', readonly=False)
    sale_split_by_warehouse = fields.Boolean(
        related='company_id.sale_split_by_warehouse', readonly=False)

    @api.onchange('sale_split_delivery')
    def _onchange_sale_split_delivery(self):
        # Turning the feature on without any criterion would do nothing:
        # pre-select the most common one.
        if self.sale_split_delivery and not (
                self.sale_split_by_date
                or self.sale_split_by_location
                or self.sale_split_by_warehouse):
            self.sale_split_by_date = True
