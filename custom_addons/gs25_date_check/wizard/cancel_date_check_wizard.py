
from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError


class GS25DateCheckCancelWizard(models.TransientModel):
    _name = "gs25.date.check.cancel.wizard"
    _description = "Hủy phiếu kiểm tra GS25"

    # 1. THÔNG TIN PHIẾU KIỂM TRA

    record_id = fields.Many2one(
        "gs25.date.check.record",
        string="Phiếu kiểm tra",
        required=True,
        readonly=True,
    )

    lot_id = fields.Many2one(
        "stock.lot",
        related="record_id.lot_id",
        string="Số lô",
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        related="record_id.product_id",
        string="Sản phẩm",
        readonly=True,
    )

    # 2. LÝ DO HỦY PHIẾU

    cancel_reason = fields.Text(
        string="Lý do hủy",
        required=True,
    )

    # 3. XÁC NHẬN HỦY PHIẾU

    def action_confirm_cancel(self):
        self.ensure_one()

        manager_group = (
            "gs25_date_check.group_gs25_date_check_manager"
        )

        if not self.env.user.has_group(manager_group):
            raise AccessError(
                "Chỉ quản lý GS25 Date Check "
                "mới được hủy phiếu kiểm tra."
            )

        if not self.record_id.exists():
            raise ValidationError(
                "Không tìm thấy phiếu kiểm tra."
            )

        reason = (self.cancel_reason or "").strip()

        if not reason:
            raise ValidationError(
                "Vui lòng nhập lý do hủy phiếu."
            )

        # Gọi phương thức xử lý trong model chính
        self.record_id._gs25_cancel(reason)

        return {
            "type": "ir.actions.act_window_close",
        }
