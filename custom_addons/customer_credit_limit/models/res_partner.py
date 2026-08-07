from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import float_compare, formatLang

# One place, one order. Every screen and every gate reads this.
CREDIT_BANDS = ['none', 'green', 'yellow', 'red']


class ResPartner(models.Model):
    _inherit = 'res.partner'

    credit_hold = fields.Boolean(
        string='On Credit Hold', tracking=True, copy=False,
        help="Blocks new orders for this customer whatever the credit position is.")
    credit_hold_reason = fields.Char(string='Hold Reason', tracking=True)
    credit_check_exempt = fields.Boolean(
        string='Exclude From Credit Control', tracking=True,
        help="Tick to switch credit control off for this customer. "
             "No warning, no block, no approval - orders always confirm.")
    credit_warn_percent_override = fields.Float(
        string='Warning At (%)',
        help="Leave at zero to use the company setting.")
    credit_block_percent_override = fields.Float(
        string='Block At (%)',
        help="Leave at zero to use the company setting.")

    credit_effective_limit = fields.Monetary(
        string='Effective Limit', compute='_compute_credit_position',
        compute_sudo=True, currency_field='currency_id')
    credit_temporary_amount = fields.Monetary(
        string='Temporary Limit', compute='_compute_credit_position',
        compute_sudo=True, currency_field='currency_id')
    credit_temporary_expiry = fields.Date(
        string='Temporary Limit Until', compute='_compute_credit_position',
        compute_sudo=True)
    credit_outstanding = fields.Monetary(
        string='Outstanding', compute='_compute_credit_position',
        compute_sudo=True, currency_field='currency_id',
        help="Unpaid invoices plus confirmed orders not yet invoiced, "
             "less credit notes and advances.")
    credit_available = fields.Monetary(
        string='Available Credit', compute='_compute_credit_position',
        compute_sudo=True, currency_field='currency_id')
    credit_used_percent = fields.Float(
        string='Credit Used (%)', compute='_compute_credit_position',
        compute_sudo=True)
    credit_overdue_amount = fields.Monetary(
        string='Overdue', compute='_compute_credit_position',
        compute_sudo=True, currency_field='currency_id')
    credit_days_overdue = fields.Integer(
        string='Days Overdue', compute='_compute_credit_position',
        compute_sudo=True, help="Age of the oldest overdue invoice.")
    credit_band = fields.Selection(
        selection=[
            ('none', 'Not checked'),
            ('green', 'Normal'),
            ('yellow', 'Warning'),
            ('red', 'Blocked'),
        ],
        string='Credit Status', compute='_compute_credit_position',
        compute_sudo=True)

    credit_approval_ids = fields.One2many(
        'customer.credit.approval', 'partner_id', string='Credit Approvals')
    credit_approval_count = fields.Integer(
        compute='_compute_credit_approval_count', compute_sudo=True)
    credit_log_ids = fields.One2many(
        'customer.credit.log', 'partner_id', string='Credit Limit History')

    # ------------------------------------------------------------------
    # settings resolution
    # ------------------------------------------------------------------
    def _credit_company(self, company=None):
        return company or self.company_id or self.env.company

    def _credit_thresholds(self, company=None):
        """Returns (warn %, block %). Customer override wins over the company."""
        company = self._credit_company(company)
        warn = self.credit_warn_percent_override or company.credit_warn_percent or 80.0
        block = self.credit_block_percent_override or company.credit_block_percent or 100.0
        return warn, block

    def _credit_temporary(self, company=None):
        """Active temporary limit granted by an approval: (amount, expiry date)."""
        self.ensure_one()
        company = self._credit_company(company)
        today = fields.Date.context_today(self)
        approvals = self.env['customer.credit.approval'].sudo().search([
            ('partner_id', '=', self.commercial_partner_id.id),
            ('company_id', '=', company.id),
            ('state', '=', 'approved'),
            ('decision', '=', 'temporary'),
            ('temporary_expiry', '>=', today),
        ], order='temporary_expiry desc', limit=1)
        return (approvals.temporary_amount, approvals.temporary_expiry) if approvals else (0.0, False)

    # ------------------------------------------------------------------
    # outstanding, batched so a list view does not fire one query per row
    # ------------------------------------------------------------------
    @api.model
    def _credit_receivable_data(self, partners, company):
        """{partner_id: {'residual', 'overdue', 'oldest_days'}} in company currency.

        Keys are real database ids. Unsaved records have no receivables.
        """
        partners = partners._origin
        result = {pid: {'residual': 0.0, 'overdue': 0.0, 'oldest_days': 0}
                  for pid in partners.ids}
        if not partners:
            return result
        today = fields.Date.context_today(self)
        lines = self.env['account.move.line'].sudo().search_read(
            [
                ('parent_state', '=', 'posted'),
                ('company_id', '=', company.id),
                ('partner_id', 'in', partners.ids),
                ('account_id.account_type', '=', 'asset_receivable'),
                ('reconciled', '=', False),
            ],
            ['partner_id', 'amount_residual', 'date_maturity', 'date'],
        )
        for line in lines:
            partner_id = line['partner_id'] and line['partner_id'][0]
            entry = result.get(partner_id)
            if entry is None:
                continue
            residual = line['amount_residual'] or 0.0
            entry['residual'] += residual
            due = line['date_maturity'] or line['date']
            if residual > 0 and due and due < today:
                entry['overdue'] += residual
                entry['oldest_days'] = max(entry['oldest_days'], (today - due).days)
        return result

    @api.model
    def _credit_open_order_amount(self, partners, company, exclude_order=None):
        """Confirmed orders not yet invoiced, converted to company currency."""
        partners = partners._origin
        result = dict.fromkeys(partners.ids, 0.0)
        if not partners:
            return result
        domain = [
            ('state', '=', 'sale'),
            ('company_id', '=', company.id),
            ('partner_id.commercial_partner_id', 'in', partners.ids),
            ('invoice_status', '!=', 'invoiced'),
        ]
        if exclude_order and exclude_order._origin:
            domain.append(('id', 'not in', exclude_order._origin.ids))
        orders = self.env['sale.order'].sudo().search(domain)
        today = fields.Date.context_today(self)
        for order in orders:
            key = order.partner_id.commercial_partner_id.id
            if key not in result:
                continue
            result[key] += order._credit_amount_to_invoice(company, today)
        return result

    # ------------------------------------------------------------------
    # the single evaluation used everywhere
    # ------------------------------------------------------------------
    def _credit_position(self, company=None, additional_amount=0.0, exclude_order=None):
        """Credit position of this customer, optionally including a pending amount.

        additional_amount must already be expressed in company currency.
        """
        self.ensure_one()
        company = self._credit_company(company)
        # In an unsaved form the record carries a NewId, which cannot be queried.
        # _origin gives the stored record, or an empty recordset for a brand new one.
        partner = self.commercial_partner_id._origin
        currency = company.currency_id
        warn, block = (partner or self)._credit_thresholds(company)

        position = {
            'company': company,
            'currency': currency,
            'base_limit': 0.0,
            'temporary_amount': 0.0,
            'temporary_expiry': False,
            'effective_limit': 0.0,
            'outstanding': 0.0,
            'document_amount': additional_amount,
            'available': 0.0,
            'used_percent': 0.0,
            'exceeded': 0.0,
            'overdue_amount': 0.0,
            'overdue_days': 0,
            'warn_percent': warn,
            'block_percent': block,
            'band': 'none',
            'reason': 'not_checked',
            'message': '',
        }

        if not partner or company.credit_control_mode == 'off' or partner.credit_check_exempt:
            return position

        receivable = self._credit_receivable_data(partner, company)[partner.id]
        open_orders = self._credit_open_order_amount(partner, company, exclude_order)[partner.id]
        temporary_amount, temporary_expiry = partner._credit_temporary(company)
        base_limit = partner.with_company(company).credit_limit or 0.0

        outstanding = receivable['residual'] + open_orders
        effective_limit = base_limit + temporary_amount
        projected = outstanding + additional_amount

        position.update({
            'base_limit': base_limit,
            'temporary_amount': temporary_amount,
            'temporary_expiry': temporary_expiry,
            'effective_limit': effective_limit,
            'outstanding': outstanding,
            'available': effective_limit - projected,
            'overdue_amount': receivable['overdue'],
            'overdue_days': receivable['oldest_days'],
        })
        if effective_limit > 0:
            position['used_percent'] = projected / effective_limit * 100.0

        # Checks in a fixed order. The first one that applies decides.
        if partner.credit_hold:
            position.update(band='red', reason='hold')
        elif (company.credit_overdue_days
                and effective_limit > 0
                and receivable['oldest_days'] > company.credit_overdue_days
                and receivable['overdue'] > 0):
            position.update(band='red', reason='overdue')
        elif effective_limit <= 0:
            position.update(band='none', reason='no_limit')
        elif position['used_percent'] >= block:
            position.update(band='red', reason='over_limit',
                            exceeded=projected - effective_limit * block / 100.0)
        elif position['used_percent'] >= warn:
            position.update(band='yellow', reason='warning')
        else:
            position.update(band='green', reason='ok')

        position['message'] = partner._credit_message(position)
        return position

    def _credit_message(self, position):
        """Plain sentence for the banner. No HTML, so it reads the same everywhere."""
        self.ensure_one()
        currency = position['currency']

        def money(amount):
            return formatLang(self.env, amount, currency_obj=currency)

        if position['reason'] == 'hold':
            reason = self.credit_hold_reason
            return _("%(name)s is on credit hold.", name=self.display_name) + (
                _(" Reason: %s", reason) if reason else '')
        if position['reason'] == 'overdue':
            return _(
                "%(name)s has %(amount)s overdue, the oldest by %(days)s days.",
                name=self.display_name,
                amount=money(position['overdue_amount']),
                days=position['overdue_days'])
        if position['reason'] == 'over_limit':
            return _(
                "This order takes %(name)s to %(pct).0f%% of the credit limit, "
                "%(amount)s over.",
                name=self.display_name,
                pct=position['used_percent'],
                amount=money(position['exceeded']))
        if position['reason'] == 'warning':
            return _(
                "%(name)s is at %(pct).0f%% of the credit limit. %(amount)s left.",
                name=self.display_name,
                pct=position['used_percent'],
                amount=money(max(position['available'], 0.0)))
        return ''

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('credit_limit', 'credit_hold', 'credit_check_exempt',
                 'credit_warn_percent_override', 'credit_block_percent_override',
                 'credit_approval_ids.state')
    def _compute_credit_position(self):
        for partner in self:
            position = partner._credit_position()
            partner.credit_effective_limit = position['effective_limit']
            partner.credit_temporary_amount = position['temporary_amount']
            partner.credit_temporary_expiry = position['temporary_expiry']
            partner.credit_outstanding = position['outstanding']
            partner.credit_available = position['available']
            partner.credit_used_percent = position['used_percent']
            partner.credit_overdue_amount = position['overdue_amount']
            partner.credit_days_overdue = position['overdue_days']
            partner.credit_band = position['band']

    def _compute_credit_approval_count(self):
        data = self.env['customer.credit.approval'].sudo()._read_group(
            [('partner_id', 'in', self.ids)], ['partner_id'], ['__count'])
        mapped = {partner.id: count for partner, count in data}
        for partner in self:
            partner.credit_approval_count = mapped.get(partner._origin.id, 0)

    # ------------------------------------------------------------------
    # protection and audit of the limit itself
    # ------------------------------------------------------------------
    CREDIT_PROTECTED_FIELDS = (
        'credit_limit', 'credit_hold', 'credit_check_exempt',
        'credit_warn_percent_override', 'credit_block_percent_override',
    )

    def write(self, vals):
        protected = [f for f in self.CREDIT_PROTECTED_FIELDS if f in vals]
        if protected and not self.env.su:
            if not self.env.user.has_group('customer_credit_limit.group_credit_approver'):
                raise AccessError(_(
                    "Only a Credit Approver can change credit settings on a customer."))
        old_limits = {}
        if 'credit_limit' in vals:
            old_limits = {p.id: p.credit_limit for p in self}
        result = super().write(vals)
        if old_limits:
            self._credit_log_limit_change(old_limits)
        return result

    def _credit_log_limit_change(self, old_limits):
        log_model = self.env['customer.credit.log'].sudo()
        for partner in self:
            old = old_limits.get(partner.id, 0.0)
            new = partner.credit_limit or 0.0
            if float_compare(old, new, precision_digits=2) == 0:
                continue
            log_model.create({
                'partner_id': partner.id,
                'company_id': (partner.company_id or self.env.company).id,
                'old_limit': old,
                'new_limit': new,
                'user_id': self.env.user.id,
                'reason': self.env.context.get('credit_log_reason') or '',
            })

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def action_open_credit_approvals(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Credit Approvals'),
            'res_model': 'customer.credit.approval',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.commercial_partner_id.id)],
            'context': {'default_partner_id': self.commercial_partner_id.id},
        }
