# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    sale_split_date = fields.Date(
        string='Split Delivery Date', index=True, readonly=True,
        help='Delivery day used to split this transfer from its sales order.')
