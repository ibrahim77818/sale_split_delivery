# -*- coding: utf-8 -*-
{
    'name': 'Split Customer Deliveries (Date, Location & Warehouse)',
    'version': '18.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Split sales order delivery orders by line expected delivery '
               'date, source location and/or warehouse',
    'description': """
Split Customer Deliveries
=========================
Sales twin of *purchase_split_grn*.

* Adds an **Expected Delivery** date on sales order lines (Odoo 16 has none),
  following the order Delivery Date and editable per line.
* Settings > Sales > Outbound Logistics: master toggle plus three independent
  criteria: split by delivery date, by source location, by warehouse.
* On confirmation, delivery orders are grouped per (day, source location,
  warehouse) combination, including multi-step (pick / pack / ship) routes.
* Post-confirmation edits of line dates or locations re-route pending moves
  and remove the delivery orders left empty.
* Full Arabic (ar_001) translation, RTL friendly views.
""",
    'author': 'Ibrahim Yahia',
    'website': 'https://www.linkedin.com/in/ibrahim-yahia',
    'license': 'LGPL-3',
    'depends': ['sale_stock'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/stock_picking_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'pre_init_hook': 'pre_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
