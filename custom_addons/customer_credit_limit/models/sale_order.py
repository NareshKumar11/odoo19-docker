from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

BANNER_CLASS = {'yellow': 'alert-warning', 'red': 'alert-danger'}
RELEASED_CLASS = 'alert-success'


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    company_currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    credit_band = fields.Selection(
        selection=[
            ('none', 'Not checked'),
            ('green', 'Normal'),
            ('yellow', 'Warning'),
            ('red', 'Blocked'),
        ],
        string='Credit Status', compute='_compute_credit_panel', compute_sudo=True)
    credit_effective_limit = fields.Monetary(
        string='Credit Limit', compute='_compute_credit_panel',
        compute_sudo=True, currency_field='company_currency_id')
    credit_outstanding = fields.Monetary(
        string='Outstanding', compute='_compute_credit_panel',
        compute_sudo=True, currency_field='company_currency_id')
    credit_order_amount = fields.Monetary(
        string='This Order', compute='_compute_credit_panel',
        compute_sudo=True, currency_field='company_currency_id')
    credit_available = fields.Monetary(
        string='Available Credit', compute='_compute_credit_panel',
        compute_sudo=True, currency_field='company_currency_id')
    credit_exceeded = fields.Monetary(
        string='Exceeded By', compute='_compute_credit_panel',
        compute_sudo=True, currency_field='company_currency_id')
    credit_used_percent = fields.Float(
        string='Credit Used (%)', compute='_compute_credit_panel', compute_sudo=True)
    credit_message = fields.Html(
        string='Credit Message', compute='_compute_credit_panel', compute_sudo=True,
        sanitize=False)
    credit_can_request = fields.Boolean(
        compute='_compute_credit_panel', compute_sudo=True)

    credit_approval_id = fields.Many2one(
        'customer.credit.approval', string='Credit Approval',
        copy=False, readonly=True)
    credit_approval_state = fields.Selection(
        related='credit_approval_id.state', string='Approval Status', readonly=True)

    # ------------------------------------------------------------------
    # amounts, always in company currency
    # ------------------------------------------------------------------
    def _credit_amount_company_currency(self):
        """Total of this order, converted to the company currency."""
        self.ensure_one()
        company = self.company_id or self.env.company
        if self.currency_id == company.currency_id:
            return self.amount_total
        return self.currency_id._convert(
            self.amount_total, company.currency_id, company,
            self.date_order.date() if self.date_order else fields.Date.context_today(self))

    def _credit_amount_to_invoice(self, company, date):
        """Part of a confirmed order not yet invoiced, in company currency."""
        self.ensure_one()
        if 'amount_to_invoice' in self._fields:
            amount = self.amount_to_invoice
        elif 'amount_invoiced' in self._fields:
            amount = self.amount_total - self.amount_invoiced
        else:
            amount = self.amount_total
        amount = max(amount, 0.0)
        if self.currency_id == company.currency_id:
            return amount
        return self.currency_id._convert(
            amount, company.currency_id, company,
            self.date_order.date() if self.date_order else date)

    # ------------------------------------------------------------------
    @api.depends('partner_id', 'amount_total', 'currency_id', 'company_id',
                 'date_order', 'state', 'credit_approval_id.state')
    def _compute_credit_panel(self):
        for order in self:
            if not order.partner_id:
                order._credit_panel_defaults()
                continue
            # A confirmed order is already inside "open orders", so it must not
            # be counted a second time here.
            exclude = order if order.state in ('sale', 'done') else None
            position = order.partner_id._credit_position(
                company=order.company_id,
                additional_amount=order._credit_amount_company_currency(),
                exclude_order=exclude)
            order.credit_band = position['band']
            order.credit_effective_limit = position['effective_limit']
            order.credit_outstanding = position['outstanding']
            order.credit_order_amount = position['document_amount']
            order.credit_available = position['available']
            order.credit_exceeded = position['exceeded']
            order.credit_used_percent = position['used_percent']
            order.credit_message = order._credit_banner(position)
            order.credit_can_request = bool(
                position['band'] == 'red'
                and order.company_id.credit_control_mode == 'approval'
                and order.state in ('draft', 'sent')
                and not order._credit_valid_release())

    def _credit_banner(self, position):
        """Colour the message here so the view needs a single field."""
        approval = self.credit_approval_id
        if self._credit_valid_release():
            decision = dict(approval._fields['decision'].selection).get(
                approval.decision, '')
            return Markup('<div class="alert %s mb-0" role="alert">%s</div>') % (
                RELEASED_CLASS,
                _("Released by %(user)s on %(date)s (%(decision)s). Reference %(ref)s.",
                  user=approval.approver_id.display_name,
                  date=fields.Date.to_string(approval.approval_date),
                  decision=decision,
                  ref=approval.name))
        if approval and approval.state == 'to_approve':
            return Markup('<div class="alert alert-info mb-0" role="alert">%s</div>') % (
                _("Waiting for credit approval. Reference %s.", approval.name))
        css = BANNER_CLASS.get(position['band'])
        if not css or not position['message']:
            return False
        return Markup('<div class="alert %s mb-0" role="alert">%s</div>') % (
            css, position['message'])

    def _credit_panel_defaults(self):
        self.ensure_one()
        self.credit_band = 'none'
        self.credit_effective_limit = 0.0
        self.credit_outstanding = 0.0
        self.credit_order_amount = 0.0
        self.credit_available = 0.0
        self.credit_exceeded = 0.0
        self.credit_used_percent = 0.0
        self.credit_message = ''
        self.credit_can_request = False

    # ------------------------------------------------------------------
    # the gate
    # ------------------------------------------------------------------
    def _credit_valid_release(self):
        self.ensure_one()
        approval = self.credit_approval_id
        return bool(approval and approval._is_release_valid_for(self))

    def _credit_gate(self):
        """Raise if this order may not be confirmed. Called from action_confirm."""
        self.ensure_one()
        company = self.company_id or self.env.company
        mode = company.credit_control_mode
        if mode in ('off', 'warn'):
            return
        if self.env.context.get('credit_approval_release') or self._credit_valid_release():
            return

        position = self.partner_id._credit_position(
            company=company,
            additional_amount=self._credit_amount_company_currency())
        if position['band'] != 'red':
            return

        # Never break a website checkout: flag it instead of raising.
        if 'website_id' in self._fields and self.website_id:
            self.message_post(body=_(
                "Credit check failed: %s Awaiting credit approval.", position['message']))
            return

        message = position['message'] or _("This customer is over their credit limit.")
        if mode == 'approval':
            raise UserError(_(
                "%(message)s\n\nUse Request Credit Approval to send this order "
                "to a credit approver.", message=message))
        raise UserError(message)

    def action_confirm(self):
        for order in self:
            order._credit_gate()
        return super().action_confirm()

    # ------------------------------------------------------------------
    def action_request_credit_approval(self):
        """Open a request prefilled with the figures the salesperson is seeing."""
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Request Credit Approval'),
            'res_model': 'customer.credit.approval',
            'view_mode': 'form',
            'views': [(self.env.ref(
                'customer_credit_limit.customer_credit_approval_request_form').id, 'form')],
            'target': 'new',
        }
        pending = self.credit_approval_id
        if pending and pending.state in ('draft', 'to_approve'):
            action['res_id'] = pending.id
            return action
        # The figures are taken server-side in create(), so they cannot be edited
        # on the way through the form.
        action['context'] = {
            'default_partner_id': self.partner_id.commercial_partner_id.id,
            'default_sale_order_id': self.id,
            'default_company_id': (self.company_id or self.env.company).id,
            # Shown in the dialog for information. The stored values are taken
            # again on the server in create().
            'default_credit_limit': self.credit_effective_limit,
            'default_outstanding': self.credit_outstanding,
            'default_order_amount': self.credit_order_amount,
            'default_exceeded_amount': self.credit_exceeded,
            'default_used_percent': self.credit_used_percent,
        }
        return action

    def action_open_credit_approval(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'customer.credit.approval',
            'res_id': self.credit_approval_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
