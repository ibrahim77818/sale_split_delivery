# -*- coding: utf-8 -*-
from odoo import models


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_stock_move_values(self, product_id, product_qty, product_uom,
                               location_id, name, origin, company_id, values):
        move_values = super()._get_stock_move_values(
            product_id, product_qty, product_uom, location_id, name, origin,
            company_id, values)
        split_date = values.get('sale_split_date')
        if split_date:
            move_values['sale_split_date'] = split_date
        location = values.get('sale_split_location_id')
        if location:
            if not isinstance(location, models.BaseModel):
                location = self.env['stock.location'].browse(location)
            move_values['sale_split_location_id'] = location.id
            source = self.location_src_id
            # Only the step that picks from stock (rule source is the line
            # location or one of its parents) is redirected; output/pack
            # steps keep their standard locations.
            if (source and location != source and location.parent_path
                    and source.parent_path
                    and location.parent_path.startswith(source.parent_path)):
                move_values['location_id'] = location.id
        return move_values
