from datetime import timedelta
from odoo import api, fields, models
from odoo.osv import expression


class GS25StockLot(models.Model):
    _inherit = "stock.lot"

    gs25_expiry_status = fields.Selection(
        selection=[
            ("no_date", "Chưa có hạn sử dụng"),
            ("normal", "Còn hạn"),
            ("near_expiry", "Cận hạn"),
            ("expired", "Hết hạn"),
        ],
        string="Trạng thái hạn sử dụng GS25",
        compute="_compute_gs25_expiry_status",
        search="_search_gs25_expiry_status",
    )

    @api.depends("expiration_date")
    def _compute_gs25_expiry_status(self):
        today = fields.Date.context_today(self)
        warning_days = 2

        for lot in self:
            if not lot.expiration_date:
                lot.gs25_expiry_status = "no_date"
                continue

            expiry_date = fields.Date.to_date(
                lot.expiration_date
            )

            if expiry_date < today:
                lot.gs25_expiry_status = "expired"

            elif expiry_date <= today + timedelta(
                days=warning_days
            ):
                lot.gs25_expiry_status = "near_expiry"

            else:
                lot.gs25_expiry_status = "normal"

    def _search_gs25_expiry_status(self, operator, value):
        if operator != "in" or not isinstance(
            value, (list, tuple)
        ):
            raise NotImplementedError(
                "Chỉ hỗ trợ tìm kiếm bằng toán tử 'in'."
            )

        today = fields.Date.context_today(self)
        warning_date = today + timedelta(days=2)

        domains = []

        if "expired" in value:
            domains.append([
                ("expiration_date", "!=", False),
                ("expiration_date", "<", today),
            ])

        if "near_expiry" in value:
            domains.append([
                ("expiration_date", ">=", today),
                (
                    "expiration_date",
                    "<",
                    warning_date + timedelta(days=1),
                ),
            ])

        if not domains:
            return [("id", "=", 0)]

        return expression.OR(domains)
