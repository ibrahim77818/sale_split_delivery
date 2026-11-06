# -*- coding: utf-8 -*-
from odoo import fields, models

SPLIT_CRITERIA = ('date', 'location', 'warehouse')


class ResCompany(models.Model):
    _inherit = 'res.company'

    sale_split_delivery = fields.Boolean(
        string='Split Customer Deliveries',
        default=False,
        help='Split the delivery orders generated from a sales order using '
             'the criteria selected below.')
    sale_split_by_date = fields.Boolean(
        string='Split by Delivery Date',
        help='Create a separate delivery order for each expected delivery '
             'day of the order lines.')
    sale_split_by_location = fields.Boolean(
        string='Split by Source Location',
        help='Pick each order line from its own stock location and group '
             'deliveries per location.')
    sale_split_by_warehouse = fields.Boolean(
        string='Split by Warehouse',
        help='Let each order line ship from a different warehouse of the '
             'same company.')

    def _sale_split_enabled(self, criterion):
        """Return True when the master switch and ``criterion`` are on."""
        self.ensure_one()
        assert criterion in SPLIT_CRITERIA, criterion
        return bool(self.sale_split_delivery
                    and self['sale_split_by_%s' % criterion])
