from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError


# A09. WIZARD TỪ CHỐI PHIẾU ĐỀ XUẤT
class GS25ReplenishmentRejectWizard(models.TransientModel):
    _name = "gs25.replenishment.reject.wizard"
    _description = "Từ chối phiếu đề xuất đặt hàng GS25"

    # 1. THÔNG TIN PHIẾU ĐỀ XUẤT
    proposal_id = fields.Many2one(
        "gs25.replenishment.proposal",
        string="Phiếu đề xuất",
        required=True,
        readonly=True,
    )

    line_count = fields.Integer(
        related="proposal_id.line_count",
        string="Số sản phẩm",
    )

    total_suggested_qty = fields.Float(
        related="proposal_id.total_suggested_qty",
        string="Tổng SL đề xuất",
    )

    # 2. LÝ DO TỪ CHỐI
    reject_reason = fields.Text(
        string="Lý do từ chối",
        required=True,
    )

    # 3. XÁC NHẬN TỪ CHỐI
    def action_confirm_reject(self):
        self.ensure_one()

        if not self.env.user.has_group(
            "gs25_replenishment.group_gs25_replenishment_manager"
        ):
            raise AccessError(
                "Chỉ quản lý cửa hàng mới được từ chối phiếu đề xuất."
            )

        if not self.proposal_id.exists():
            raise ValidationError("Không tìm thấy phiếu đề xuất.")

        self.proposal_id._gs25_reject(self.reject_reason)

        return {"type": "ir.actions.act_window_close"}
