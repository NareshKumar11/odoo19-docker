{
    'name': 'Customer Credit Limit',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Block sales orders over the credit limit, with approval and temporary limits',
    'description': """
Customer Credit Limit
=====================

Odoo warns when a customer passes their credit limit but cannot stop anything.
This module adds:

* Available credit shown on the customer and on the quotation, with a colour
* Confirmation blocked when the customer is on hold, overdue, or over the limit
* One-screen approval: release this order, or grant a temporary limit that expires
* Optional blocking at delivery validation and invoice posting
* Read-only log of every credit limit change

Works with no configuration. Six settings in Accounting > Settings.
""",
    'author': '',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['sale_management', 'account', 'stock'],
    'data': [
        'security/credit_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/ir_cron.xml',
        'data/mail_templates.xml',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/credit_approval_views.xml',
        'views/credit_log_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
