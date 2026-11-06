# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """Create and fill the new stored computed columns of sale.order.line in SQL.

    When the column already exists the ORM does not recompute the field for
    every existing line at install time, which keeps installation fast on
    databases with many sales order lines.
    """
    cr = env.cr
    _logger.info("sale_split_delivery: pre-filling sale.order.line columns")
    cr.execute("""
        ALTER TABLE sale_order_line
            ADD COLUMN IF NOT EXISTS expected_delivery_date timestamp,
            ADD COLUMN IF NOT EXISTS delivery_warehouse_id integer,
            ADD COLUMN IF NOT EXISTS delivery_location_id integer
    """)
    cr.execute("""
        UPDATE sale_order_line sol
           SET expected_delivery_date = so.commitment_date,
               delivery_warehouse_id = so.warehouse_id
          FROM sale_order so
         WHERE so.id = sol.order_id
           AND sol.display_type IS NULL
    """)
    cr.execute("""
        UPDATE sale_order_line sol
           SET delivery_location_id = wh.lot_stock_id
          FROM stock_warehouse wh
         WHERE wh.id = sol.delivery_warehouse_id
    """)
