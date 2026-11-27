from odoo import Command, api, fields, models
from odoo.exceptions import ValidationError


# A11. WIZARD PHẢN HỒI CỦA KHO TỔNG (MÔ PHỎNG)
class GS25DwResponseWizard(models.TransientModel):
    _name = "gs25.dw.response.wizard"
    _description = "Phản hồi của kho tổng GS25 (mô phỏng)"

    # 1. THÔNG TIN ĐƠN ĐẶT HÀNG
    purchase_id = fields.Many2one(
        "purchase.order",
        string="Đơn đặt hàng",
        required=True,
        readonly=True,
    )

    mode = fields.Selection(
        [
            ("partial", "Xác nhận một phần"),
            ("reject", "Từ chối đơn"),
        ],
        string="Phản hồi",
        required=True,
        readonly=True,
        default="partial",
    )

    line_ids = fields.One2many(
        "gs25.dw.response.wizard.line",
        "wizard_id",
        string="Số lượng kho tổng đáp ứng",
        compute="_compute_line_ids",
        store=True,
        readonly=False,
    )

    # 2. GHI CHÚ PHẢN HỒI
    note = fields.Text(
        string="Lý do / ghi chú của kho tổng",
        required=True,
    )

    @api.depends("purchase_id", "mode")
    def _compute_line_ids(self):
        for wizard in self:
            commands = [Command.clear()]

            if wizard.mode == "partial":
                commands += [
                    Command.create({
                        "purchase_line_id": line.id,
                        "available_qty": line.product_qty,
                    })
                    for line in wizard.purchase_id.order_line
                    if not line.display_type
                ]

            wizard.line_ids = commands

    # 3. XÁC NHẬN PHẢN HỒI
    def action_confirm(self):
        self.ensure_one()

        if not self.purchase_id.exists():
            raise ValidationError("Không tìm thấy đơn đặt hàng.")

        if self.mode == "reject":
            self.purchase_id._gs25_dw_reject(self.note)
        else:
            self.purchase_id._gs25_dw_partial(
                {
                    line.purchase_line_id.id: line.available_qty
                    for line in self.line_ids
                },
                self.note,
            )

        return {"type": "ir.actions.act_window_close"}


class GS25DwResponseWizardLine(models.TransientModel):
    _name = "gs25.dw.response.wizard.line"
    _description = "Dòng phản hồi của kho tổng GS25"

    wizard_id = fields.Many2one(
        "gs25.dw.response.wizard",
        required=True,
        ondelete="cascade",
    )

    purchase_line_id = fields.Many2one(
        "purchase.order.line",
        string="Dòng đơn",
        required=True,
    )

    product_id = fields.Many2one(
        related="purchase_line_id.product_id",
        string="Sản phẩm",
    )

    ordered_qty = fields.Float(
        related="purchase_line_id.product_qty",
        string="SL cửa hàng đặt",
    )

    uom_id = fields.Many2one(
        related="purchase_line_id.product_uom_id",
        string="Đơn vị",
    )

    available_qty = fields.Float(
        string="SL kho tổng đáp ứng",
        digits="Product Unit",
    )
